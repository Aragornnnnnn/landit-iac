# LAN-351 시나리오 고정 질문 TTS 게시 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** production의 활성 고정 질문 120개를 지정된 Aura-2 voice의 MP3로 생성하고, 검증된 manifest와 함께 기존 shared content S3 bucket에 신규 immutable 객체로 게시한다.

**Architecture:** Python 3.12 표준 라이브러리만 사용하는 단일 작업 도구가 source JSON을 검증하고, OpenRouter 호출·재시도·resume·manifest 생성과 승인형 S3 업로드를 담당한다. production DB export는 읽기 전용 SQL로 `/tmp` snapshot을 만들며, MP3는 저장소 밖에 두고 최종 manifest만 커밋한다. 샘플 3개 승인과 S3 업로드 승인은 각각 별도 게이트다.

**Tech Stack:** Python 3.12 표준 라이브러리, `unittest`, OpenRouter `/api/v1/audio/speech`, AWS CLI 2.35+, S3, macOS `afinfo` 또는 `ffprobe`.

**Spec:** `docs/superpowers/specs/2026-08-25-lan-351-scenario-question-audio-design.md`.

## Global Constraints

- production source는 `scenario`, `scenario_question`, `scenario_question_language_variant`의 `ACTIVE`, `EN`/`KR` 데이터만 읽는다.
- 정확히 40개 시나리오와 120개 질문, 시나리오별 `displayOrder=1..3`을 요구한다.
- voice는 Chloe `aura-2-luna-en`, Marco `aura-2-hyperion-en`, Teddy `aura-2-draco-en`이며 model은 모두 `deepgram/aura-2`다.
- OpenRouter 출력은 `response_format=mp3`이고 S3 `Content-Type`은 `audio/mpeg`다.
- generation fingerprint는 질문 원문, model, voice, response format의 canonical JSON SHA-256이다.
- 작업 동시성은 4, 최초 요청 포함 최대 시도는 4회, 연결 timeout은 10초, 전체 timeout은 120초다.
- MP3와 secret은 저장소에 커밋하지 않는다.
- BE·AI 코드, runtime IAM, DB schema와 Terraform 리소스는 변경하지 않는다.
- 샘플 승인 전 전체 생성, 로컬 전수 검증 전 S3 업로드, 사용자 승인 전 S3 변경을 실행하지 않는다.
- S3 key를 덮어쓰거나 기존 객체를 삭제하지 않는다.

---

## 파일 구조

- `scripts/scenario_question_audio.py`: source 검증, sample 선택, OpenRouter 생성, resume, manifest 완성, S3 dry-run·업로드 CLI를 한 파일에서 제공한다.
- `scripts/tests/test_scenario_question_audio.py`: 외부 네트워크와 AWS를 mock한 단위 테스트로 계약, 재시도, resume와 업로드 gate를 검증한다.
- `manifests/scenario-question-audio/lan-351.json`: 전체 생성 완료 뒤 커밋하는 최종 manifest다.
- `docs/content-storage.md`: 고정 질문 오디오 prefix, immutable metadata와 후속 runtime 조회 원칙을 기록한다.
- `checklist.md`: 실제 단계와 승인 gate 상태를 갱신한다.
- `context-notes.md`: source digest, 샘플 승인, 생성 결과, S3 승인·검증 증거를 기록한다.
- `/tmp/landit-lan-351-audio/source.json`: production 읽기 전용 export다. 커밋하지 않는다.
- `/tmp/landit-lan-351-audio/mp3/`: 생성 MP3와 resume 상태다. 커밋하지 않는다.

### Task 1: source 계약과 generation fingerprint

**Files:**
- Create: `scripts/scenario_question_audio.py`.
- Create: `scripts/tests/test_scenario_question_audio.py`.
- Modify: `checklist.md`.
- Modify: `context-notes.md`.

**Interfaces:**
- Consumes: source JSON의 `schemaVersion`, `environment`, `targetLocale`, `baseLocale`, `assets[]`.
- Produces: `load_source(path: Path) -> SourceSnapshot`, `validate_source(snapshot: SourceSnapshot) -> None`, `generation_contract(asset: SourceAsset) -> dict[str, str]`, `generation_fingerprint(asset: SourceAsset) -> str`, `select_sample_ids(snapshot: SourceSnapshot) -> set[int]`.

- [ ] **Step 1: source 검증 실패 테스트를 작성한다.**

`scripts/tests/test_scenario_question_audio.py` 첫 줄에 `# LAN-351 고정 질문 오디오 배치 도구의 계약을 검증한다.`를 넣고 `unittest.TestCase`에서 다음 fixture를 만든다.

```python
def make_valid_snapshot() -> SourceSnapshot:
    assets = []
    question_id = 1
    scenario_id = 1
    for character_id, scenario_count in (("chloe", 3), ("marco", 8), ("teddy", 29)):
        for _ in range(scenario_count):
            for order in (1, 2, 3):
                assets.append(SourceAsset(
                    scenario_id=scenario_id,
                    scenario_question_id=question_id,
                    display_order=order,
                    character_id=character_id,
                    question_text=f"Question {question_id}?",
                ))
                question_id += 1
            scenario_id += 1
    return SourceSnapshot(
        schema_version=1,
        environment="production",
        target_locale="EN",
        base_locale="KR",
        assets=tuple(assets),
    )
```

다음 테스트를 먼저 작성한다.

```python
def test_validate_source_rejects_wrong_counts(self):
    snapshot = replace(make_valid_snapshot(), assets=make_valid_snapshot().assets[:-1])
    with self.assertRaisesRegex(ValueError, "120 questions"):
        validate_source(snapshot)

def test_validate_source_rejects_missing_display_order(self):
    snapshot = make_valid_snapshot()
    changed = replace(snapshot.assets[0], display_order=2)
    with self.assertRaisesRegex(ValueError, "display orders"):
        validate_source(replace(snapshot, assets=(changed,) + snapshot.assets[1:]))

def test_validate_source_rejects_duplicate_question_id(self):
    snapshot = make_valid_snapshot()
    duplicate = replace(snapshot.assets[1], scenario_question_id=1)
    with self.assertRaisesRegex(ValueError, "duplicate question id"):
        validate_source(replace(snapshot, assets=(snapshot.assets[0], duplicate) + snapshot.assets[2:]))

def test_validate_source_rejects_unknown_character(self):
    snapshot = make_valid_snapshot()
    unknown = replace(snapshot.assets[0], character_id="unknown")
    with self.assertRaisesRegex(ValueError, "unsupported character"):
        validate_source(replace(snapshot, assets=(unknown,) + snapshot.assets[1:]))

def test_validate_source_accepts_40_scenarios_and_expected_voice_distribution(self):
    snapshot = make_valid_snapshot()
    validate_source(snapshot)
    self.assertEqual(120, len(snapshot.assets))
```

유효 fixture는 Chloe 3개 시나리오, Marco 8개, Teddy 29개를 만들고 각 시나리오에 질문 3개를 둔다.

- [ ] **Step 2: 실패 테스트를 실행한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.SourceContractTests -v`.

Expected: `ModuleNotFoundError` 또는 `load_source`·`validate_source` import 실패.

- [ ] **Step 3: 최소 source model과 검증을 구현한다.**

`scripts/scenario_question_audio.py` 첫 줄에 `# production 시나리오 고정 질문을 MP3로 생성하고 immutable S3 객체로 게시한다.`를 넣는다. 외부 package 없이 `dataclasses`, `hashlib`, `json`, `pathlib`를 사용한다.

```python
VOICE_BY_CHARACTER = {
    "chloe": "aura-2-luna-en",
    "marco": "aura-2-hyperion-en",
    "teddy": "aura-2-draco-en",
}
MODEL = "deepgram/aura-2"
RESPONSE_FORMAT = "mp3"
EXPECTED_SCENARIO_COUNTS = {"chloe": 3, "marco": 8, "teddy": 29}
EXPECTED_QUESTION_COUNTS = {"chloe": 9, "marco": 24, "teddy": 87}
```

`SourceAsset`과 `SourceSnapshot`은 다음 필드의 frozen dataclass로 만들고, `validate_source`는 전역 수·캐릭터별 수·질문 ID 유일성·시나리오별 순서·빈 원문을 모두 검사해 `ValueError`를 발생시킨다.

```python
@dataclass(frozen=True)
class SourceAsset:
    scenario_id: int
    scenario_question_id: int
    display_order: int
    character_id: str
    question_text: str

@dataclass(frozen=True)
class SourceSnapshot:
    schema_version: int
    environment: str
    target_locale: str
    base_locale: str
    assets: tuple[SourceAsset, ...]
```

- [ ] **Step 4: fingerprint와 sample 선택 테스트를 작성한다.**

```python
def test_fingerprint_changes_when_text_changes(self):
    asset = make_valid_snapshot().assets[0]
    changed = replace(asset, question_text="A different question?")
    changed_voice = replace(asset, character_id="marco")
    self.assertNotEqual(generation_fingerprint(asset), generation_fingerprint(changed))
    self.assertNotEqual(generation_fingerprint(asset), generation_fingerprint(changed_voice))

def test_generation_contract_uses_exact_fields(self):
    asset = make_valid_snapshot().assets[0]
    self.assertEqual({
        "model": "deepgram/aura-2",
        "providerVoiceId": "aura-2-luna-en",
        "questionText": "Question 1?",
        "responseFormat": "mp3",
    }, generation_contract(asset))

def test_select_samples_returns_one_question_per_character(self):
    snapshot = make_valid_snapshot()
    selected = select_sample_ids(snapshot)
    selected_characters = {asset.character_id for asset in snapshot.assets if asset.scenario_question_id in selected}
    self.assertEqual(3, len(selected))
    self.assertEqual({"chloe", "marco", "teddy"}, selected_characters)
```

canonical JSON은 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`로 직렬화한다. 샘플은 캐릭터별 `(len(questionText.encode("utf-8")), scenarioQuestionId)` 정렬의 중앙 항목이다.

- [ ] **Step 5: fingerprint와 sample 선택을 구현하고 테스트를 통과시킨다.**

`argparse`에 `validate-source --source PATH`를 추가해 유효한 source의 scenario·question·character별 수와 SHA-256만 출력하게 한다.

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.SourceContractTests -v`.

Expected: 모든 source·fingerprint·sample 테스트 PASS.

- [ ] **Step 6: 첫 논리 커밋을 만든다.**

```bash
git add scripts/scenario_question_audio.py scripts/tests/test_scenario_question_audio.py checklist.md context-notes.md
git commit -m "feat: LAN-351 TTS 생성 입력 계약을 검증한다"
```

### Task 2: OpenRouter 생성, 재시도와 resume

**Files:**
- Modify: `scripts/scenario_question_audio.py`.
- Modify: `scripts/tests/test_scenario_question_audio.py`.

**Interfaces:**
- Consumes: Task 1의 `SourceAsset`, `generation_contract`, `generation_fingerprint`, `select_sample_ids`.
- Produces: `SpeechHttpResult`, `OpenRouterSpeechClient.synthesize(asset: SourceAsset) -> SpeechResponse`, `generate_assets(snapshot, work_dir, sample_only) -> list[GeneratedAsset]`, `validate_mp3(path: Path, probe_runner=subprocess.run) -> AudioProbe`, `load_generation_state(path: Path) -> dict[str, GeneratedAsset]`.

- [ ] **Step 1: 성공 응답과 secret 비노출 테스트를 작성한다.**

fake transport가 `status=200`, `Content-Type=audio/mpeg`, `X-Generation-Id=generation-1`, MP3 bytes를 반환하게 한다.

```python
def test_client_sends_exact_tts_contract_and_returns_binary_metadata(self):
    calls = []
    def requester(payload, headers, connect_timeout, total_timeout):
        calls.append((payload, headers, connect_timeout, total_timeout))
        return SpeechHttpResult(200, {"Content-Type": "audio/mpeg", "X-Generation-Id": "generation-1"}, b"ID3audio")
    response = OpenRouterSpeechClient("secret-key", requester=requester).synthesize(make_valid_snapshot().assets[0])
    self.assertEqual("generation-1", response.generation_id)
    self.assertEqual(b"ID3audio", response.body)
    self.assertEqual(10, calls[0][2])
    self.assertEqual(120, calls[0][3])
    self.assertEqual({
        "model": "deepgram/aura-2",
        "input": "Question 1?",
        "voice": "aura-2-luna-en",
        "response_format": "mp3",
    }, calls[0][0])
    self.assertNotIn("secret-key", json.dumps(calls[0][0]))

def test_error_message_never_contains_api_key(self):
    def requester(payload, headers, connect_timeout, total_timeout):
        return SpeechHttpResult(401, {"Content-Type": "application/json"}, b'{"error":"unauthorized"}')
    with self.assertRaises(Exception) as caught:
        OpenRouterSpeechClient("secret-key", requester=requester).synthesize(make_valid_snapshot().assets[0])
    self.assertNotIn("secret-key", str(caught.exception))
```

요청 URL은 `https://openrouter.ai/api/v1/audio/speech`이고 body에는 `model`, `input`, `voice`, `response_format` 네 필드만 허용한다.

- [ ] **Step 2: 테스트가 실패하는지 확인한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.OpenRouterSpeechClientTests -v`.

Expected: `OpenRouterSpeechClient`가 없어 FAIL.

- [ ] **Step 3: OpenRouter client 최소 구현을 작성한다.**

다음 immutable result type을 추가한다.

```python
@dataclass(frozen=True)
class SpeechHttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes

@dataclass(frozen=True)
class SpeechResponse:
    body: bytes
    generation_id: str
```

production requester는 `http.client.HTTPSConnection("openrouter.ai", timeout=10)`으로 먼저 `connect()`하고, 연결 뒤 socket timeout을 120초로 바꾼 다음 `POST /api/v1/audio/speech` 응답을 읽는다. client에는 `(payload, headers, connect_timeout, total_timeout) -> SpeechHttpResult` requester를 주입할 수 있게 한다. production 구현은 key를 `OPENROUTER_API_KEY` 환경변수에서 읽되 예외 문자열에 포함하지 않는다.

- [ ] **Step 4: 재시도 분류 테스트를 작성한다.**

```python
def test_retries_429_then_succeeds_on_fourth_attempt(self):
    results = iter([
        SpeechHttpResult(429, {}, b"rate limited"),
        SpeechHttpResult(429, {}, b"rate limited"),
        SpeechHttpResult(429, {}, b"rate limited"),
        SpeechHttpResult(200, {"Content-Type": "audio/mpeg", "X-Generation-Id": "g-4"}, b"ID3audio"),
    ])
    sleeps = []
    client = OpenRouterSpeechClient("key", requester=lambda *args: next(results), sleep=sleeps.append, jitter=lambda: 0.5)
    self.assertEqual("g-4", client.synthesize(make_valid_snapshot().assets[0]).generation_id)
    self.assertEqual([1.5, 2.5, 4.5], sleeps)

def test_retries_server_and_connection_errors(self):
    for first_result in (500, 502, 503, TimeoutError("timeout")):
        calls = []
        def requester(*args):
            calls.append(None)
            if len(calls) == 1:
                if isinstance(first_result, Exception):
                    raise first_result
                return SpeechHttpResult(first_result, {}, b"server error")
            return SpeechHttpResult(200, {"Content-Type": "audio/mpeg", "X-Generation-Id": "ok"}, b"ID3audio")
        OpenRouterSpeechClient("key", requester=requester, sleep=lambda seconds: None, jitter=lambda: 0).synthesize(make_valid_snapshot().assets[0])
        self.assertEqual(2, len(calls))

def test_does_not_retry_permanent_http_errors(self):
    for status in (400, 401, 402, 404):
        calls = []
        client = OpenRouterSpeechClient("key", requester=lambda *args: calls.append(status) or SpeechHttpResult(status, {}, b"error"))
        with self.assertRaises(PermanentTtsError):
            client.synthesize(make_valid_snapshot().assets[0])
        self.assertEqual([status], calls)

def test_rejects_non_mpeg_content_type_and_empty_body(self):
    for result in (
        SpeechHttpResult(200, {"Content-Type": "application/json", "X-Generation-Id": "bad"}, b"{}"),
        SpeechHttpResult(200, {"Content-Type": "audio/mpeg", "X-Generation-Id": "bad"}, b""),
    ):
        with self.assertRaises(InvalidAudioResponse):
            OpenRouterSpeechClient("key", requester=lambda *args: result).synthesize(make_valid_snapshot().assets[0])
```

sleep 함수와 random 함수는 주입해 테스트에서는 실제로 기다리지 않는다. 시도 간격은 `1+jitter`, `2+jitter`, `4+jitter`다.

- [ ] **Step 5: 재시도 정책을 구현하고 client 테스트를 통과시킨다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.OpenRouterSpeechClientTests -v`.

Expected: 모든 HTTP 계약·재시도·secret 테스트 PASS.

- [ ] **Step 6: MP3 probe와 resume 실패 테스트를 작성한다.**

```python
def test_validate_mp3_accepts_afinfo_duration(self):
    completed = subprocess.CompletedProcess(["afinfo", "audio.mp3"], 0, "estimated duration: 1.25 sec", "")
    probe = validate_mp3(Path("audio.mp3"), probe_runner=lambda *args, **kwargs: completed)
    self.assertGreater(probe.duration_seconds, 0)

def test_validate_mp3_rejects_probe_failure_or_zero_duration(self):
    for completed in (
        subprocess.CompletedProcess(["afinfo", "audio.mp3"], 1, "", "invalid"),
        subprocess.CompletedProcess(["afinfo", "audio.mp3"], 0, "estimated duration: 0.0 sec", ""),
    ):
        with self.assertRaises(InvalidMp3Error):
            validate_mp3(Path("audio.mp3"), probe_runner=lambda *args, **kwargs: completed)

def test_generate_assets_reuses_matching_verified_file(self):
    with tempfile.TemporaryDirectory() as directory:
        client = Mock()
        snapshot = make_valid_snapshot()
        sample_ids = select_sample_ids(snapshot)
        for asset in snapshot.assets:
            if asset.scenario_question_id in sample_ids:
                seed_verified_generation_state(Path(directory), asset, b"ID3audio")
        results = generate_assets(snapshot, Path(directory), sample_only=True, client=client)
        self.assertEqual(sample_ids, {item.scenario_question_id for item in results})
        client.synthesize.assert_not_called()

def test_generate_assets_regenerates_tampered_file(self):
    with tempfile.TemporaryDirectory() as directory:
        snapshot = make_valid_snapshot()
        sample_ids = select_sample_ids(snapshot)
        asset = next(item for item in snapshot.assets if item.scenario_question_id in sample_ids)
        seed_verified_generation_state(Path(directory), asset, b"ID3audio")
        audio_path_for(Path(directory), asset).write_bytes(b"tampered")
        client = Mock()
        client.synthesize.return_value = SpeechResponse(b"ID3replacement", "replacement")
        generate_assets(make_valid_snapshot(), Path(directory), sample_only=True, client=client, probe_runner=successful_probe)
        client.synthesize.assert_called_once()

def test_sample_only_generates_exactly_three_assets(self):
    with tempfile.TemporaryDirectory() as directory:
        client = Mock()
        client.synthesize.return_value = SpeechResponse(b"ID3audio", "generation")
        results = generate_assets(make_valid_snapshot(), Path(directory), sample_only=True, client=client, probe_runner=successful_probe)
        self.assertEqual(3, len(results))
        self.assertEqual(3, client.synthesize.call_count)
```

`afinfo`가 없으면 `ffprobe`를 사용하고 둘 다 없으면 생성 전에 명시적으로 실패한다. 파일은 같은 디렉터리의 `.part`에 쓴 뒤 probe와 SHA-256 검증이 성공해야 원자적으로 `.mp3`로 이동한다.

테스트 helper는 다음 계약을 갖는다.

- `successful_probe(*args, **kwargs)`는 `afinfo` duration 1.25초의 `CompletedProcess`를 반환한다.
- `seed_verified_generation_state(work_dir, asset, body)`는 body를 예상 MP3 경로에 쓰고 일치하는 `GeneratedAsset` 한 건을 `state.json`에 저장해 반환한다.
- `audio_path_for(work_dir, asset)`는 `{work_dir}/mp3/{scenarioQuestionId}-{generationFingerprint}.mp3`를 반환한다.

- [ ] **Step 7: 동시성 4의 생성·resume을 구현한다.**

`ThreadPoolExecutor(max_workers=4)`를 사용한다. worker는 고유한 파일만 쓰고, main thread가 완료 future를 받을 때 `state.json`을 임시 파일에 쓴 뒤 `os.replace`로 갱신한다. state에는 question ID, fingerprint, byte size, audio SHA-256과 generation ID만 저장한다.

다음 frozen dataclass를 사용한다.

```python
@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float

@dataclass(frozen=True)
class GeneratedAsset:
    scenario_question_id: int
    generation_fingerprint: str
    path: Path
    audio_byte_size: int
    audio_sha256: str
    generation_id: str
    duration_seconds: float
```

`argparse`에 `generate --source PATH --work-dir PATH [--sample-only]`와 `verify --source PATH --work-dir PATH [--sample-only]`를 추가한다. `generate`는 완료·재사용·실패 수를, `verify`는 검증된 캐릭터별 수와 총 bytes를 출력한다.

- [ ] **Step 8: 생성 계층 테스트를 통과시킨다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.GenerationTests -v`.

Expected: probe, concurrency, sample-only와 resume 테스트 PASS.

- [ ] **Step 9: 두 번째 논리 커밋을 만든다.**

```bash
git add scripts/scenario_question_audio.py scripts/tests/test_scenario_question_audio.py
git commit -m "feat: OpenRouter TTS 생성을 재개 가능하게 만든다"
```

### Task 3: manifest 완성 및 승인형 S3 업로드

**Files:**
- Modify: `scripts/scenario_question_audio.py`.
- Modify: `scripts/tests/test_scenario_question_audio.py`.
- Modify: `docs/content-storage.md`.

**Interfaces:**
- Consumes: Task 2의 검증된 `GeneratedAsset` 120개와 `SourceSnapshot`.
- Produces: `build_manifest(snapshot, generated_assets) -> dict`, `verify_manifest(manifest, work_dir) -> None`, `plan_s3_upload(manifest, bucket, aws_runner=subprocess.run) -> UploadPlan`, `execute_s3_upload(plan, execute=False) -> UploadResult`.

- [ ] **Step 1: manifest 완전성 실패 테스트를 작성한다.**

테스트 helper는 다음 계약을 갖는다.

- `make_generated_assets()`는 유효 source의 120개 질문마다 고유 fingerprint, 임시 MP3 경로, byte size, SHA-256, generation ID와 양수 duration을 가진 `GeneratedAsset`을 반환한다.
- `seed_full_manifest(work_dir)`는 120개 MP3와 state를 work directory에 쓰고 `(snapshot, generated_assets, manifest)`를 반환한다.

```python
def test_manifest_requires_all_120_generated_assets(self):
    with self.assertRaisesRegex(ValueError, "120 generated assets"):
        build_manifest(make_valid_snapshot(), make_generated_assets()[:-1])

def test_manifest_contains_source_and_audio_digests_and_exact_s3_keys(self):
    manifest = build_manifest(make_valid_snapshot(), make_generated_assets())
    first = manifest["assets"][0]
    self.assertRegex(manifest["source"]["snapshotSha256"], r"^[0-9a-f]{64}$")
    self.assertRegex(first["audioSha256"], r"^[0-9a-f]{64}$")
    self.assertEqual(
        f"content/scenario-question-audio/1/{first['generationFingerprint']}.mp3",
        first["s3Key"],
    )

def test_manifest_is_canonical_and_has_stable_sha256(self):
    manifest = build_manifest(make_valid_snapshot(), make_generated_assets())
    first = canonical_manifest_bytes(manifest)
    second = canonical_manifest_bytes(json.loads(first))
    self.assertEqual(first, second)
    self.assertTrue(first.endswith(b"\n"))
    self.assertEqual(hashlib.sha256(first).hexdigest(), manifest_sha256(manifest))

def test_verify_manifest_detects_changed_audio_bytes(self):
    with tempfile.TemporaryDirectory() as directory:
        snapshot, generated, manifest = seed_full_manifest(Path(directory))
        generated[0].path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "audio sha256 mismatch"):
            verify_manifest(manifest, Path(directory))
```

manifest JSON은 UTF-8, `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`와 마지막 newline 하나로 저장한다.

- [ ] **Step 2: 실패를 확인하고 manifest 구현을 추가한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio.ManifestTests -v`.

Expected before implementation: import 또는 assertion FAIL.

Run after implementation: 같은 명령이 PASS.

- [ ] **Step 3: S3 dry-run과 overwrite 금지 테스트를 작성한다.**

S3 테스트 helper는 다음 계약을 갖는다.

- `valid_manifest()`는 `build_manifest(make_valid_snapshot(), make_generated_assets())` 결과를 반환한다.
- `matching_head_results(manifest)`는 manifest의 120개 MP3와 content-addressed manifest key에 대해 일치하는 `ContentLength`, `ContentType`, `CacheControl`, `Metadata`를 반환한다.
- `RecordingAwsRunner`는 받은 argument list를 `calls`에 저장하고 `head-object`, `put-object`별 고정 JSON과 exit code를 반환한다. 실제 subprocess나 AWS를 호출하지 않는다.

```python
def test_upload_defaults_to_dry_run_without_aws_put(self):
    runner = RecordingAwsRunner(head_results={})
    plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)
    result = execute_s3_upload(plan, execute=False, aws_runner=runner)
    self.assertEqual(0, result.uploaded)
    self.assertFalse(any("put-object" in call for call in runner.calls))

def test_upload_uses_if_none_match_star_and_required_metadata(self):
    runner = RecordingAwsRunner(head_results={})
    plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)
    execute_s3_upload(plan, execute=True, aws_runner=runner)
    put_call = next(
        call for call in runner.calls
        if "put-object" in call and call[call.index("--key") + 1].endswith(".mp3")
    )
    self.assertIn("--if-none-match", put_call)
    self.assertIn("*", put_call)
    self.assertIn("--content-type", put_call)
    self.assertIn("audio/mpeg", put_call)

def test_existing_matching_object_is_reused(self):
    runner = RecordingAwsRunner(head_results=matching_head_results(valid_manifest()))
    plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)
    self.assertEqual(121, plan.reused_count)
    self.assertEqual(0, plan.conflict_count)

def test_existing_mismatched_object_fails_without_overwrite(self):
    head_results = matching_head_results(valid_manifest())
    first_key = valid_manifest()["assets"][0]["s3Key"]
    head_results[first_key]["Metadata"]["audio-sha256"] = "0" * 64
    runner = RecordingAwsRunner(head_results=head_results)
    with self.assertRaisesRegex(ValueError, "existing object conflict"):
        plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)
    self.assertFalse(any("put-object" in call for call in runner.calls))

def test_manifest_upload_runs_after_all_mp3_objects(self):
    runner = RecordingAwsRunner(head_results={})
    execute_s3_upload(plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner), execute=True, aws_runner=runner)
    put_keys = [call[call.index("--key") + 1] for call in runner.calls if "put-object" in call]
    self.assertTrue(put_keys[-1].startswith("content/scenario-question-audio/manifests/"))

def test_post_upload_head_matches_manifest_metadata(self):
    runner = RecordingAwsRunner(head_results={})
    plan = plan_s3_upload(valid_manifest(), "bucket", aws_runner=runner)
    result = execute_s3_upload(plan, execute=True, aws_runner=runner)
    self.assertEqual(121, result.verified)
    self.assertEqual(0, result.conflicts)
```

AWS CLI 호출은 argument list로 실행하고 shell을 사용하지 않는다. MP3 `put-object`에는 `--if-none-match *`, `--content-type audio/mpeg`, `--cache-control public, max-age=31536000, immutable`, `--metadata source-sha256=0123456789abcdef,audio-sha256=fedcba9876543210,model=deepgram/aura-2,voice=aura-2-luna-en` 형식의 값을 포함한다.

- [ ] **Step 4: dry-run 기본값과 명시적 `--execute` gate를 구현한다.**

`upload` subcommand는 `--execute`가 없으면 신규·재사용·충돌 예상 수와 key만 출력한다. `--execute`가 있을 때만 MP3 120개를 먼저 올리고 전수 `head-object` 검증 뒤 manifest를 마지막 completion marker로 올린다.

`argparse`에 `build-manifest --source PATH --work-dir PATH --output PATH`, `verify --manifest PATH`, `upload --manifest PATH --work-dir PATH --bucket NAME [--execute]`를 추가한다. 다음 immutable result type을 사용한다.

```python
@dataclass(frozen=True)
class UploadPlan:
    new_keys: tuple[str, ...]
    reused_keys: tuple[str, ...]
    conflict_keys: tuple[str, ...]

    @property
    def reused_count(self) -> int:
        return len(self.reused_keys)

    @property
    def conflict_count(self) -> int:
        return len(self.conflict_keys)

@dataclass(frozen=True)
class UploadResult:
    uploaded: int
    verified: int
    conflicts: int
```

- [ ] **Step 5: 전체 단위 테스트를 실행한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio -v`.

Expected: 모든 테스트 PASS, 실제 OpenRouter·AWS 호출 0회.

- [ ] **Step 6: 콘텐츠 저장 문서를 갱신한다.**

`docs/content-storage.md`에 다음 계약을 추가한다.

```text
content/scenario-question-audio/{scenarioQuestionId}/{generationFingerprint}.mp3
content/scenario-question-audio/manifests/{manifestSha256}.json
```

고정 질문 MP3는 shared private bucket의 신규 immutable 콘텐츠이며, 후속 runtime은 manifest의 정확한 key를 사용하고 MP3 bytes를 단순 연결하지 않는다고 기록한다.

- [ ] **Step 7: 세 번째 논리 커밋을 만든다.**

```bash
git add scripts/scenario_question_audio.py scripts/tests/test_scenario_question_audio.py docs/content-storage.md
git commit -m "feat: 고정 질문 오디오 manifest와 안전한 게시 절차를 추가한다"
```

### Task 4: production source snapshot 생성과 계약 검증

**Files:**
- Create temporarily: `/tmp/landit-lan-351-audio/source.json`.
- Modify: `context-notes.md`.
- Modify: `checklist.md`.

**Interfaces:**
- Consumes: production SSM `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`를 프로세스 메모리에서만 사용한 read-only connection.
- Produces: Task 1 source schema의 정렬된 JSON과 source SHA-256.

- [ ] **Step 1: production 상태를 재조회한다.**

다음 SQL만 사용한다.

```sql
SELECT
  s.id AS scenario_id,
  sq.id AS scenario_question_id,
  sq.display_order,
  s.character_id,
  qlv.question_text
FROM scenario s
JOIN scenario_question sq
  ON sq.scenario_id = s.id
 AND sq.status = 'ACTIVE'
JOIN scenario_question_language_variant qlv
  ON qlv.scenario_question_id = sq.id
 AND qlv.status = 'ACTIVE'
 AND qlv.target_locale = 'EN'
 AND qlv.base_locale = 'KR'
WHERE s.status = 'ACTIVE'
ORDER BY s.id, sq.display_order, sq.id;
```

connection과 credential 원문은 출력하지 않는다. SQL 결과는 source JSON 필드로만 기록한다.

- [ ] **Step 2: source JSON을 검증한다.**

Run: `python3 scripts/scenario_question_audio.py validate-source --source /tmp/landit-lan-351-audio/source.json`.

Expected: `40 scenarios, 120 questions, chloe=9, marco=24, teddy=87`와 source SHA-256을 출력하고 exit 0.

- [ ] **Step 3: 초기 production audit과 drift를 비교한다.**

초기 MD5 `9c79b5aec3333eb7022dca5b9da10f39`와 동일한 필드·정렬 방식의 MD5를 다시 계산한다. 다르면 질문 ID, 원문 hash, 캐릭터와 순서의 변경 목록을 출력하고 작업을 멈춘다. 같으면 source SHA-256을 `context-notes.md`에 기록한다.

- [ ] **Step 4: 검증 기록을 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: LAN-351 production 질문 snapshot을 검증한다"
```

### Task 5: 캐릭터별 샘플 생성과 사람 승인 gate

**Files:**
- Create outside repository: `/tmp/landit-lan-351-audio/mp3/*.mp3` 3개.
- Modify: `context-notes.md`.
- Modify: `checklist.md`.

**Interfaces:**
- Consumes: Task 4 source JSON, 유효한 `OPENROUTER_API_KEY`.
- Produces: median UTF-8 길이 기준 Chloe·Marco·Teddy 샘플 각 1개와 검증 metadata.

- [ ] **Step 1: 잔액과 key 인증을 재확인한다.**

Run: `curl --fail --silent https://openrouter.ai/api/v1/credits -H "Authorization: Bearer ${OPENROUTER_API_KEY}" | jq '{remaining:(.data.total_credits-.data.total_usage)}'`.

Expected: HTTP 200과 0보다 큰 `remaining`. key 원문은 출력하지 않는다.

- [ ] **Step 2: sample-only 생성을 실행한다.**

Run: `python3 scripts/scenario_question_audio.py generate --source /tmp/landit-lan-351-audio/source.json --work-dir /tmp/landit-lan-351-audio --sample-only`.

Expected: OpenRouter 호출 3건, `audio/mpeg` 3건, MP3 probe 3건 PASS.

- [ ] **Step 3: 샘플 파일과 metadata를 검증한다.**

Run: `python3 scripts/scenario_question_audio.py verify --source /tmp/landit-lan-351-audio/source.json --work-dir /tmp/landit-lan-351-audio --sample-only`.

Expected: Chloe 1개, Marco 1개, Teddy 1개의 byte size, duration과 SHA-256이 모두 유효하다.

- [ ] **Step 4: 세 샘플을 사용자에게 제공하고 작업을 멈춘다.**

Codex 앱에서 절대 경로 MP3 세 개를 재생 가능한 링크로 제공한다. 사용자가 voice, 억양, 잘림·침묵 여부를 승인하기 전 Task 6을 실행하지 않는다.

- [ ] **Step 5: 승인 결과를 기록하고 커밋한다.**

```bash
git add checklist.md context-notes.md
git commit -m "docs: LAN-351 캐릭터별 TTS 샘플 검수를 기록한다"
```

### Task 6: 전체 120개 생성과 최종 manifest

**Files:**
- Create outside repository: `/tmp/landit-lan-351-audio/mp3/*.mp3` 120개.
- Create: `manifests/scenario-question-audio/lan-351.json`.
- Modify: `context-notes.md`.
- Modify: `checklist.md`.

**Interfaces:**
- Consumes: 승인된 샘플 state와 Task 4 source JSON.
- Produces: 검증된 전체 MP3 120개와 최종 manifest.

- [ ] **Step 1: 전체 생성을 실행한다.**

Run: `python3 scripts/scenario_question_audio.py generate --source /tmp/landit-lan-351-audio/source.json --work-dir /tmp/landit-lan-351-audio`.

Expected: 샘플 3개는 resume하고 나머지 117개만 호출한다. 최종 상태는 Chloe 9개, Marco 24개, Teddy 87개다.

- [ ] **Step 2: manifest를 만든다.**

Run: `python3 scripts/scenario_question_audio.py build-manifest --source /tmp/landit-lan-351-audio/source.json --work-dir /tmp/landit-lan-351-audio --output manifests/scenario-question-audio/lan-351.json`.

Expected: asset 120개, source SHA-256 하나, 고유 generation fingerprint 120개와 audio SHA-256 120개.

- [ ] **Step 3: 로컬 전수 검증을 실행한다.**

Run: `python3 scripts/scenario_question_audio.py verify --source /tmp/landit-lan-351-audio/source.json --work-dir /tmp/landit-lan-351-audio --manifest manifests/scenario-question-audio/lan-351.json`.

Expected: 120/120 MP3 probe, size와 SHA-256 PASS. 실패가 하나라도 있으면 manifest를 커밋하지 않는다.

- [ ] **Step 4: 전체 테스트와 저장소 검증을 실행한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio -v`.

Run: `git diff --check`.

Expected: 모든 단위 테스트 PASS, whitespace 오류 0개.

- [ ] **Step 5: manifest와 검증 기록을 커밋한다.**

```bash
git add manifests/scenario-question-audio/lan-351.json checklist.md context-notes.md
git commit -m "feat: LAN-351 고정 질문 오디오 manifest를 확정한다"
```

### Task 7: S3 dry-run, 별도 승인, 게시와 원격 검증

**Files:**
- Modify: `context-notes.md`.
- Modify: `checklist.md`.

**Interfaces:**
- Consumes: Task 6 최종 manifest와 MP3 120개, shared Terraform output `content_bucket_name`.
- Produces: 신규 immutable MP3 120개, content-addressed manifest 한 개와 원격 검증 증거.

- [ ] **Step 1: shared bucket과 dry-run을 읽기 전용으로 확인한다.**

Run: `AWS_PROFILE=landit terraform -chdir=environments/shared output -raw content_bucket_name`.

Run: `python3 scripts/scenario_question_audio.py upload --manifest manifests/scenario-question-audio/lan-351.json --work-dir /tmp/landit-lan-351-audio --bucket "${LAN351_CONTENT_BUCKET}"`.

Expected: `new=121, reused=0, conflicts=0` 또는 재실행이면 검증된 reused 수를 포함한다. `put-object` 호출은 0회다.

- [ ] **Step 2: 사용자에게 변경 목록을 보고하고 멈춘다.**

신규 MP3 수, manifest 수, 총 bytes, prefix, 충돌 수와 기존 객체 overwrite·delete가 없음을 보고한다. 사용자에게 실제 S3 업로드 승인을 요청한다.

- [ ] **Step 3: 승인된 경우에만 업로드를 실행한다.**

Run: `python3 scripts/scenario_question_audio.py upload --manifest manifests/scenario-question-audio/lan-351.json --work-dir /tmp/landit-lan-351-audio --bucket "${LAN351_CONTENT_BUCKET}" --execute`.

Expected: MP3 120개를 먼저 게시·검증하고 manifest를 마지막에 게시한다. 기존 key와 불일치가 발견되면 즉시 실패하고 overwrite하지 않는다.

- [ ] **Step 4: 원격 객체를 전수 검증한다.**

Run: `python3 scripts/scenario_question_audio.py upload --manifest manifests/scenario-question-audio/lan-351.json --work-dir /tmp/landit-lan-351-audio --bucket "${LAN351_CONTENT_BUCKET}"`.

Expected: `new=0, reused=121, conflicts=0`, content type·cache control·metadata·byte size 일치 121/121.

- [ ] **Step 5: 최종 검증과 작업 기록을 커밋한다.**

Run: `python3 -m unittest scripts.tests.test_scenario_question_audio -v`.

Run: `git diff --check`.

Run: `git status --short`.

`context-notes.md`에는 source SHA-256, 캐릭터별 수, 총 bytes, manifest SHA-256, 신규·재사용·충돌 수와 실제 명령 결과만 기록한다. bucket name, secret, DB host와 credential은 기록하지 않는다.

```bash
git add checklist.md context-notes.md
git commit -m "docs: LAN-351 고정 질문 오디오 게시를 검증한다"
```
