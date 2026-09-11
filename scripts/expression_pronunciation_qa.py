# LAN-453 발음 자산 TTS 품질 검사 — 생성된 mp3를 파일마다 자동검사하고 불합격은 재합성한다.
#
# TTS(deepgram aura-2) 출력은 비결정적이며 실측 불량률이 ~9%다 (무음 > 엉뚱한 단어 > 꼬리 잡음).
# expression_pronunciation_audio.py의 generate는 "디코딩 가능·길이 양수"만 보므로, 그 위에
# 다음 두 검사를 얹는다. 둘 다 통과해야 합격이다.
#
#   1. 무음 검사  — 16kHz mono로 디코딩한 전체 RMS가 -50 dBFS 이하면 불합격
#   2. 전사 검사  — Whisper(small.en, temperature=0, condition_on_previous_text=False)로
#                  전사해 기대 텍스트와 토큰 단위로 대조. 동음이의어는 CMU 발음사전으로
#                  음소 비교해 흡수하고(to=two, way=weigh), 숫자 표기는 단어로 정규화한다.
#                  Whisper는 무음에 "Thanks for watching!" 같은 환각을 내므로 1번과 병행한다.
#
# 불합격은 최대 --max-resynth 회 재합성한다. 입력을 (원문, "원문.", "원문,") 순으로 돌리면
# 자동완성("Thank"→"Thank you")을 억제하는 데 도움이 된다. 재합성해도 S3 키는 바뀌지 않는다
# (키 = 생성계약(모델·보이스·원문) 해시). 소진되면 실패 목록으로 분리해 사람 판정에 넘긴다.
#
# 위 두 검사로도 남는 불합격은 `adjudicate`로 오디오 판정 모델에 다시 묻는다. 단어 뒤 "크"
# 같은 비언어 잡음 꼬리는 RMS·Whisper 어느 것으로도 못 잡는데, 오디오를 직접 듣는 모델은
# 이를 defect로 보고할 수 있다. 다만 모델도 완벽하지 않으니 게시 전 `sample`로 뽑은 무작위
# 파일을 사람이 들어 보는 절차를 생략하지 말 것.
#
# 사용법 (generate 완료 후, upload 전):
#   python3 scripts/expression_pronunciation_qa.py check  --source tts_source.json --work-dir work/ \
#       --report work/qa_report.json --resynth
#   python3 scripts/expression_pronunciation_qa.py adjudicate --source tts_source.json --work-dir work/ \
#       --report work/qa_report.json --sample-passed 200        # 기록만; 반영은 --apply
#   python3 scripts/expression_pronunciation_qa.py sample --source tts_source.json --work-dir work/ \
#       --report work/qa_report.json --out-dir samples/ --count 45
#
# 의존성: ffmpeg(PATH), faster-whisper, pronouncing, num2words — 별도 venv 권장 (README 참고)
from __future__ import annotations

import argparse
import array
import dataclasses
import hashlib
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import expression_pronunciation_audio as epa  # noqa: E402

SILENCE_RMS_DBFS = -50.0
DEFAULT_MAX_RESYNTH = 6
DEFAULT_WORKERS = 4
DEFAULT_WHISPER_MODEL = "small.en"
# Apple Silicon에서는 mlx-whisper(GPU)가 faster-whisper(CPU int8)보다 5배쯤 빠르다.
# 둘 다 같은 small.en 가중치라 판정은 거의 같다 (90개 실측 4건 차이, 모두 애매한 단어).
MLX_MODEL_REPO_BY_NAME = {
    "small.en": "mlx-community/whisper-small.en-mlx",
    "base.en": "mlx-community/whisper-base.en-mlx",
    "medium.en": "mlx-community/whisper-medium.en-mlx",
}
# 재합성 입력 변형. 원문 → 마침표 → 쉼표 순으로 순환한다.
VARIANT_SUFFIXES = ("", ".", ",")
# 같은 (locale, 기대→전사) 오류가 이 횟수 이상 반복되면 보이스의 계통적 실패로 본다.
SYSTEMATIC_FAILURE_THRESHOLD = 3
# 불합격 원본 보관 상한. 전량 보관하면 수천 개라 사람 판정용 표본만 남긴다.
DEFAULT_KEEP_FAILED_MAX = 15

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})
_SEPARATORS = re.compile(r"[—–\-/]+")
_NON_WORD = re.compile(r"[^a-z0-9' ]+")
_DIGITS = re.compile(r"\d+")
# Whisper는 "ten dollars"를 "$10"으로, "eleventh"를 "11th"로 적는다. 숫자를 단어로 풀기 전에
# 통화·서수를 먼저 풀어야 기대 텍스트와 토큰이 맞는다 (LAN-453·471 실측 불합격의 주요 원인).
_CURRENCY = re.compile(r"\$(\d+)(?:\.(\d{2}))?")
_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b")
_PERCENT = re.compile(r"(\d+)\s?%")
_CONTRACTIONS = {
    "i'm": "i am",
    "i'll": "i will",
    "i've": "i have",
    "i'd": "i would",
    "you're": "you are",
    "you'll": "you will",
    "you've": "you have",
    "you'd": "you would",
    "we're": "we are",
    "we'll": "we will",
    "we've": "we have",
    "we'd": "we would",
    "they're": "they are",
    "they'll": "they will",
    "they've": "they have",
    "they'd": "they would",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "that's": "that is",
    "there's": "there is",
    "here's": "here is",
    "what's": "what is",
    "who's": "who is",
    "where's": "where is",
    "how's": "how is",
    "let's": "let us",
    "can't": "cannot",
    "won't": "will not",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "wouldn't": "would not",
    "couldn't": "could not",
    "shouldn't": "should not",
    "gonna": "going to",
    "wanna": "want to",
    "gotta": "got to",
}


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    rms_dbfs: float
    transcript: str
    reason: str


@dataclass
class AssetOutcome:
    asset_id: str
    text: str
    kind: str
    accent_locale: str
    passed: bool
    attempts: int
    first_reason: str
    last_reason: str
    last_transcript: str
    last_rms_dbfs: float
    audio_sha256: str


# ---------------------------------------------------------------- 텍스트 정규화


def _digits_to_words(token: str) -> str:
    from num2words import num2words

    def replace(match: re.Match) -> str:
        return " " + num2words(int(match.group(0))).replace("-", " ").replace(",", "") + " "

    return _DIGITS.sub(replace, token)


def _currency_to_words(text: str) -> str:
    from num2words import num2words

    def replace(match: re.Match) -> str:
        dollars = int(match.group(1))
        words = f"{num2words(dollars)} {'dollar' if dollars == 1 else 'dollars'}"
        if match.group(2) and int(match.group(2)):
            words += f" {num2words(int(match.group(2)))} cents"
        return " " + words.replace("-", " ").replace(",", "") + " "

    return _CURRENCY.sub(replace, text)


def _ordinals_to_words(text: str) -> str:
    from num2words import num2words

    def replace(match: re.Match) -> str:
        return " " + num2words(int(match.group(1)), to="ordinal").replace("-", " ") + " "

    return _ORDINAL.sub(replace, text)


def normalize_tokens(text: str) -> list[str]:
    lowered = text.translate(_APOSTROPHES).lower()
    lowered = _PERCENT.sub(r" \1 percent ", lowered)
    lowered = _currency_to_words(lowered)
    lowered = _ordinals_to_words(lowered)
    lowered = _SEPARATORS.sub(" ", lowered)
    lowered = _digits_to_words(lowered)
    lowered = _NON_WORD.sub(" ", lowered)
    tokens = []
    for raw in lowered.split():
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def expand_contractions(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.extend(_CONTRACTIONS.get(token, token).split())
    return expanded


def _phoneme_sets(word: str) -> set[str]:
    import pronouncing

    phones = pronouncing.phones_for_word(word)
    return {re.sub(r"\d", "", entry) for entry in phones}


def tokens_match(expected: str, heard: str) -> bool:
    if expected == heard:
        return True
    expected_phones = _phoneme_sets(expected)
    if not expected_phones:
        return False
    return bool(expected_phones & _phoneme_sets(heard))


def sequences_match(expected: list[str], heard: list[str]) -> bool:
    if len(expected) != len(heard):
        return False
    return all(tokens_match(e, h) for e, h in zip(expected, heard))


def _phoneme_edit_distance(a: list[str], b: list[str]) -> int:
    previous = list(range(len(b) + 1))
    for i, item in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (item != other))
            )
        previous = current
    return previous[-1]


# 사람이 직접 들어 정상으로 확인한 (억양, 기대 단어, Whisper 전사) 쌍. 음소 거리 규칙으로도
# 못 거르는 억양 특성이다 — 호주 보이스의 /aɪ/는 [ɑe]로 열려 "I'll"이 "아울"처럼 들리고
# Whisper는 이를 "oh"로 적는다 (2026-09-06 선녀 청취 확인, 28건 전부 정상).
LISTENED_OK_PAIRS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("EN_AU", "i'll", "oh"),
        ("EN_AU", "move", "news"),
        # 호주 영어는 비권설음이라 "year"의 r이 빠져 "yeah"처럼 난다 (2026-09-11 선녀 청취, 5건 전부 정상)
        ("EN_AU", "year", "yeah"),
    }
)


def single_word_near_match(expected: str, heard: str) -> bool:
    """단독 단어 클립용 완화 판정: 음소 편집거리 1 이하면 같은 단어로 본다.

    맥락 없는 0.5초 클립에서 Whisper는 an/and, call/cool, a/I, we're/with처럼 음소 하나
    차이를 구분하지 못한다 (2026-09-06 실측: 6회 재합성 후 남은 90개를 사람이 들으니 전부
    정상). 문장·표현 클립은 맥락이 있어 정확하므로 이 완화를 적용하지 않는다.
    """
    expected_phones = _phoneme_sets(expected)
    heard_phones = _phoneme_sets(heard)
    if not expected_phones or not heard_phones:
        return False
    return any(
        _phoneme_edit_distance(e.split(), h.split()) <= 1
        for e in expected_phones
        for h in heard_phones
    )


def transcript_matches(
    expected_text: str,
    transcript: str,
    *,
    single_word_lenient: bool = False,
    accent_locale: str | None = None,
) -> bool:
    expected = normalize_tokens(expected_text)
    heard = normalize_tokens(transcript)
    if sequences_match(expected, heard):
        return True
    if sequences_match(expand_contractions(expected), expand_contractions(heard)):
        return True
    # 붙여쓰기·띄어쓰기 차이("log in"↔"login", "secondhand"↔"second hand", "meet up"↔
    # "meetup")는 소리가 같으므로 공백을 무시하고 한 번 더 비교한다 (LAN-471 실측).
    if expected and heard and "".join(expected) == "".join(heard):
        return True
    if single_word_lenient and len(expected) == 1 and len(heard) == 1:
        if (accent_locale, expected[0], heard[0]) in LISTENED_OK_PAIRS:
            return True
        return single_word_near_match(expected[0], heard[0])
    return False


# ---------------------------------------------------------------- 오디오 검사


def decode_pcm16k(path: Path, runner: Callable = subprocess.run) -> array.array:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-",
    ]
    completed = runner(command, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed for {path}")
    samples = array.array("h")
    samples.frombytes(completed.stdout[: len(completed.stdout) // 2 * 2])
    return samples


def rms_dbfs(samples: array.array) -> float:
    if len(samples) == 0:
        return -math.inf
    total = 0
    for value in samples:
        total += value * value
    rms = math.sqrt(total / len(samples)) / 32768.0
    if rms <= 0:
        return -math.inf
    return 20 * math.log10(rms)


DEFAULT_TRANSCRIBE_TIMEOUT_SECONDS = 90.0


class SubprocessTranscriber:
    """전사를 자식 프로세스에서 돌리고 요청마다 타임아웃을 건다.

    Whisper는 드물게 한 클립에서 디코딩 루프에 빠져 영영 안 돌아온다 (2026-09-06 실측:
    GPU 대기 상태로 14분 무진전). GPU 연산은 스레드에서 취소할 수 없으므로 자식 프로세스를
    죽이고 다시 띄우는 방식으로만 복구된다. 타임아웃된 클립은 빈 전사로 돌려 불합격 처리
    → 재합성 루프로 넘어간다. 요청은 잠금으로 직렬화한다 (자식 하나, GPU 하나).
    """

    def __init__(
        self,
        backend: str,
        model_name: str,
        timeout_seconds: float = DEFAULT_TRANSCRIBE_TIMEOUT_SECONDS,
    ) -> None:
        self._backend = backend
        self._model_name = model_name
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self.timeouts = 0

    def _spawn(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(Path(__file__).resolve()),
                "transcribe-worker",
                "--backend",
                self._backend,
                "--model",
                self._model_name,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def _kill(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.wait()
            self._process = None

    def __call__(self, path: Path) -> str:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                self._kill()
                self._process = self._spawn()
            process = self._process
            result: dict[str, str] = {}

            def read() -> None:
                assert process.stdin and process.stdout
                process.stdin.write(json.dumps({"path": str(path)}) + "\n")
                process.stdin.flush()
                result["line"] = process.stdout.readline()

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            reader.join(self._timeout)
            if reader.is_alive() or not result.get("line"):
                self.timeouts += 1
                self._kill()
                return ""
            return json.loads(result["line"]).get("text", "")

    def close(self) -> None:
        with self._lock:
            self._kill()


def run_transcribe_worker(backend: str, model_name: str) -> int:
    """SubprocessTranscriber의 자식 쪽. stdin 한 줄(JSON path) → stdout 한 줄(JSON text)."""
    transcribe = build_transcriber(backend, model_name, workers=1, in_process=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        try:
            text = transcribe(Path(request["path"]))
        except Exception as error:  # noqa: BLE001 — 자식은 죽지 말고 실패를 보고한다
            text = ""
            sys.stderr.write(f"transcribe failed: {error}\n")
        sys.stdout.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


class MlxWhisperTranscriber:
    """mlx-whisper 래퍼. GPU 연산이라 스레드 안전하지 않으므로 잠금으로 직렬화한다.

    전사만 직렬이고 디코딩·RMS·재합성은 다른 스레드에서 계속 병렬로 돈다.
    """

    def __init__(self, model_name: str) -> None:
        import mlx_whisper

        self._transcribe = mlx_whisper.transcribe
        self._repo = MLX_MODEL_REPO_BY_NAME.get(model_name, model_name)
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> str:
        with self._lock:
            result = self._transcribe(
                str(path),
                path_or_hf_repo=self._repo,
                language="en",
                temperature=0,
                condition_on_previous_text=False,
                fp16=True,
                verbose=None,
            )
        return result["text"].strip()


def build_transcriber(
    backend: str,
    model_name: str,
    workers: int,
    *,
    in_process: bool = False,
    timeout_seconds: float = DEFAULT_TRANSCRIBE_TIMEOUT_SECONDS,
) -> Callable[[Path], str]:
    """기본은 타임아웃이 있는 자식 프로세스 전사. in_process=True는 자식 안에서만 쓴다."""
    if backend == "auto":
        try:
            import mlx_whisper  # noqa: F401

            backend = "mlx"
        except ImportError:
            backend = "faster"
    if not in_process:
        return SubprocessTranscriber(backend, model_name, timeout_seconds)
    if backend == "mlx":
        return MlxWhisperTranscriber(model_name)
    return WhisperTranscriber(model_name, workers)


class WhisperTranscriber:
    """faster-whisper 래퍼. 모델 로드는 한 번, 여러 스레드가 공유한다."""

    def __init__(self, model_name: str, workers: int) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model_name, device="cpu", compute_type="int8", num_workers=workers
        )

    def __call__(self, path: Path) -> str:
        segments, _ = self._model.transcribe(
            str(path),
            language="en",
            temperature=0,
            condition_on_previous_text=False,
            beam_size=5,
            without_timestamps=True,
            vad_filter=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def check_audio(
    path: Path,
    expected_text: str,
    transcribe: Callable[[Path], str] | None,
    *,
    decoder: Callable[[Path], array.array] = decode_pcm16k,
    single_word_lenient: bool = False,
    accent_locale: str | None = None,
) -> CheckResult:
    """transcribe가 None이면 무음 검사만 한다 (단어 클립처럼 전사 오탐이 많은 종류용)."""
    level = rms_dbfs(decoder(path))
    if level <= SILENCE_RMS_DBFS:
        return CheckResult(False, level, "", f"silence rms={level:.1f}dBFS")
    if transcribe is None:
        return CheckResult(True, level, "", "")
    transcript = transcribe(path)
    if transcript_matches(
        expected_text,
        transcript,
        single_word_lenient=single_word_lenient,
        accent_locale=accent_locale,
    ):
        return CheckResult(True, level, transcript, "")
    return CheckResult(False, level, transcript, f"transcript mismatch: {transcript!r}")


# ---------------------------------------------------------------- 재합성


# 무음 불합격의 재합성에 쓰는 변형. 호주 보이스 실측(2026-09-07): 기능어 단독 입력에서
# "a." 4/4·"her." 3/4가 무음, 원문 1/4~5/8, 쉼표 변형 "a,"·"her,"·"I'll,"는 12회 중 1회.
SILENCE_RETRY_SUFFIX = ","
# 짧은 기능어 단독 클립은 무음이 아니어도 쉼표 입력이 훨씬 안정적이다. LAN-471 실측(기능어
# 12개 × 3억양 × 각 3회): 쉼표 없이 합격 67%·무음 18·오인식 18 → 쉼표 89%·무음 4·오인식 8.
# 사람 청취로 쉼표 버전 억양이 자연스러운 것도 확인했다. 일반 단어는 효과를 재지 않았으므로
# 원래 변형 순환을 쓴다. 생성계약(키)은 원문 기준 그대로라 재합성해도 S3 키는 바뀌지 않는다.
FUNCTION_WORDS = frozenset(
    {
        "the", "a", "an", "to", "of", "in", "on", "at", "and", "or", "it", "is", "i", "you",
        "he", "she", "we", "they", "for", "with", "by", "from", "my", "your", "his", "her",
        "our", "their", "this", "that", "be", "are", "was", "were", "do", "so", "but", "as",
        "if", "up", "me", "him", "us", "them", "can", "will", "i'll", "i'm", "it's",
    }
)


def is_function_word(asset: epa.SourceAsset) -> bool:
    return asset.kind == epa.KIND_WORD and (
        asset.text.translate(_APOSTROPHES).lower().strip(".,!?") in FUNCTION_WORDS
    )


def variant_text(text: str, attempt: int, *, suffix: str | None = None) -> str:
    if suffix is None:
        suffix = VARIANT_SUFFIXES[attempt % len(VARIANT_SUFFIXES)]
    if not suffix:
        return text
    return text.rstrip(".,!?") + suffix


def _kept_count(directory: Path) -> int:
    return sum(1 for _ in directory.glob("*.mp3")) if directory.is_dir() else 0


def resynthesize(
    asset: epa.SourceAsset,
    attempt: int,
    work_dir: Path,
    client: epa.OpenRouterSpeechClient,
    *,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
    keep_failed_dir: Path | None = None,
    keep_failed_max: int = DEFAULT_KEEP_FAILED_MAX,
    suffix: str | None = None,
) -> epa.GeneratedAsset:
    """원문 대신 변형 텍스트로 합성하되, 파일 경로·핑거프린트는 원문 자산 기준을 유지한다.

    keep_failed_dir를 주면 덮어쓰기 전의 불합격 파일을 `{자산id}-attempt{n}.mp3`로 보관한다
    (사람 판정·TTS 불량 유형 분석용).
    """
    variant = dataclasses.replace(
        asset, text=variant_text(asset.text, attempt, suffix=suffix)
    )
    response = client.synthesize(variant)
    final_path = epa.audio_path_for(work_dir, asset)
    if (
        keep_failed_dir is not None
        and final_path.is_file()
        and _kept_count(keep_failed_dir) < keep_failed_max
    ):
        keep_failed_dir.mkdir(parents=True, exist_ok=True)
        # 파일명만 보고도 무슨 텍스트여야 하는지 알 수 있게 기대 텍스트를 붙인다.
        slug = re.sub(r"[^A-Za-z0-9]+", "_", asset.text).strip("_")[:40]
        kept_name = (
            f"{epa.asset_id(asset).replace('/', '-')}_{slug}-attempt{attempt + 1}.mp3"
        )
        shutil.copyfile(final_path, keep_failed_dir / kept_name)
    temporary_path = Path(f"{final_path}.part")
    try:
        temporary_path.write_bytes(response.body)
        probe = epa.validate_mp3(
            temporary_path, probe_runner=probe_runner, probe_name=probe_name
        )
        os.replace(temporary_path, final_path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return epa.GeneratedAsset(
        asset_id=epa.asset_id(asset),
        expression_id=asset.expression_id,
        accent_locale=asset.accent_locale,
        kind=asset.kind,
        word_order=asset.word_order,
        generation_fingerprint=epa.generation_fingerprint(asset),
        path=final_path,
        audio_byte_size=len(response.body),
        audio_sha256=hashlib.sha256(response.body).hexdigest(),
        generation_id=response.generation_id,
        duration_seconds=probe.duration_seconds,
    )


# ---------------------------------------------------------------- Gemini 2차 판정

# Whisper 전사 대조는 단독 단어 클립에서 오탐이 많고(1음소 차이·억양 특성), 단어 뒤에 붙는
# 비언어 잡음 꼬리는 RMS로도 전사로도 잡히지 않는다. 오디오를 직접 듣는 모델에 불합격분만
# 다시 물어 사람 청취 대상을 좁힌다.
#
# 프롬프트는 LAN-373 스파이크 교훈을 따른다 — 열린 질문("무슨 소리가 들리나")은 환각을
# 부르므로 판정은 반드시 양자택일로 받고, 진단용 heard/problem은 참고값으로만 쓴다.
ADJUDICATION_PROMPT = """Transcribe this audio clip exactly as spoken, word for word.
Then report whether anything is wrong with the recording itself.

Do not guess at words you cannot hear. If the clip is silent, leave "heard" empty.

Answer with JSON only, no markdown fences:
{"heard": "<exact words you hear>", "defect": "<none|silent|truncated|noise|unintelligible>"}

defect meanings:
  none            - clean speech, nothing cut off, no stray sounds
  silent          - no speech at all
  truncated       - a word is cut off at the start or end
  noise           - a click, breath, or stray syllable around the speech
  unintelligible  - speech is there but cannot be made out"""

ADJUDICATION_MODEL = epa.JUDGMENT_MODEL
DEFAULT_ADJUDICATION_WORKERS = 8


@dataclass(frozen=True)
class Adjudication:
    """오디오 판정 결과. clean이 None이면 모델이 판별하지 못한 것이다."""

    clean: bool | None
    heard: str | None
    problem: str | None


def adjudicate_audio(
    api_key: str,
    audio_path: Path,
    expected_text: str,
    *,
    accent_locale: str | None = None,
    single_word_lenient: bool = False,
    requester: Callable = epa.request_judgment,
) -> Adjudication:
    """오디오를 듣고 받아 적게 한 뒤, 기대 텍스트와의 대조는 이 코드가 한다.

    기대 텍스트를 프롬프트에 넣으면 모델이 그대로 따라 적는다 (2026-09-10 실측: "Good
    question" 클립에 기대 텍스트를 "purple elephant sandwich"로 주자 그대로 정상이라고
    답했다). 그래서 모델에는 무엇이 들려야 하는지 알려주지 않고, 판정은 Whisper와 같은
    정규화 규칙으로 여기서 내린다.
    """
    import base64

    payload = {
        "model": ADJUDICATION_MODEL,
        "temperature": 0.0,
        "max_tokens": 1000,
        "reasoning": {"effort": "low"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ADJUDICATION_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(audio_path.read_bytes()).decode(
                                "ascii"
                            ),
                            "format": "mp3",
                        },
                    },
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    result = requester(payload, headers, 10, 60)
    if result.status != 200:
        raise epa.AccentVerificationError(
            f"adjudication request failed with HTTP {result.status}"
        )
    # OpenRouter는 일시 장애 때 200이면서 choices가 비어 있는 몸통을 준다 — fail-closed.
    try:
        body = json.loads(result.body.decode("utf-8"))
        raw = (body["choices"][0]["message"]["content"] or "").strip()
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise epa.AccentVerificationError(
            f"adjudication response body is malformed: {type(error).__name__}"
        ) from error
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return Adjudication(None, None, None)
    heard = parsed.get("heard") if isinstance(parsed.get("heard"), str) else None
    defect = parsed.get("defect") if isinstance(parsed.get("defect"), str) else None
    if heard is None or defect is None:
        return Adjudication(None, heard, defect)
    if defect == "unintelligible":
        return Adjudication(None, heard, defect)
    if defect != "none":
        return Adjudication(False, heard, defect)
    matches = transcript_matches(
        expected_text,
        heard,
        single_word_lenient=single_word_lenient,
        accent_locale=accent_locale,
    )
    return Adjudication(matches, heard, defect if matches else "wrong_words")


def run_adjudication(
    report_path: Path,
    work_dir: Path,
    snapshot: epa.SourceSnapshot,
    api_key: str,
    *,
    workers: int = DEFAULT_ADJUDICATION_WORKERS,
    sample_passed: int = 0,
    seed: int = 0,
    apply_verdicts: bool = False,
    adjudicator: Callable[..., Adjudication] = adjudicate_audio,
    progress: Callable[[str], None] = print,
) -> dict:
    """불합격 자산(및 선택적으로 합격 표본)을 오디오 모델에 다시 물어 보고서에 기록한다.

    apply_verdicts가 False면 판정만 기록하고 passed는 건드리지 않는다 — 합격/불합격을
    조용히 뒤집지 않기 위해 반영은 명시적으로 요청받는다.
    """
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assets = {item["assetId"]: item for item in payload["assets"]}
    by_id = {epa.asset_id(a): a for a in snapshot.assets}

    targets = [item for item in payload["assets"] if not item["passed"]]
    passed_pool = [item for item in payload["assets"] if item["passed"]]
    if sample_passed > 0 and passed_pool:
        # 합격 표본도 함께 물어 "Whisper는 통과시켰지만 실제로는 불량"인 비율을 잰다.
        rng = random.Random(seed)
        targets += rng.sample(passed_pool, min(sample_passed, len(passed_pool)))

    lock = threading.Lock()
    done = 0
    errors = 0

    def judge(item: dict) -> tuple[dict, Adjudication | None]:
        asset = by_id.get(item["assetId"])
        if asset is None:
            return item, None
        try:
            verdict = adjudicator(
                api_key,
                epa.audio_path_for(work_dir, asset),
                item["text"],
                accent_locale=asset.accent_locale,
                single_word_lenient=asset.kind == epa.KIND_WORD,
            )
        except epa.AccentVerificationError:
            return item, None
        return item, verdict

    progress(f"adjudicating {len(targets)} clips with {ADJUDICATION_MODEL}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for item, verdict in executor.map(judge, targets):
            with lock:
                done += 1
                if verdict is None:
                    errors += 1
                    assets[item["assetId"]]["geminiClean"] = None
                else:
                    row = assets[item["assetId"]]
                    row["geminiClean"] = verdict.clean
                    row["geminiHeard"] = verdict.heard
                    row["geminiProblem"] = verdict.problem
                if done % 50 == 0:
                    progress(f"  {done}/{len(targets)} judged, {errors} unavailable")

    judged = [assets[i["assetId"]] for i in targets]
    failed_judged = [r for r in judged if not r["passed"]]
    passed_judged = [r for r in judged if r["passed"]]
    would_flip = [r for r in failed_judged if r.get("geminiClean") is True]
    still_bad = [r for r in failed_judged if r.get("geminiClean") is False]
    unresolved = [r for r in failed_judged if r.get("geminiClean") is None]
    false_negatives = [r for r in passed_judged if r.get("geminiClean") is False]

    if apply_verdicts:
        for row in would_flip:
            row["passed"] = True
            row["lastReason"] = f"gemini-clean: {row.get('lastReason', '')}".strip()

    summary = {
        "model": ADJUDICATION_MODEL,
        "judged": len(targets),
        "failedJudged": len(failed_judged),
        "geminiSaysClean": len(would_flip),
        "geminiConfirmsDefect": len(still_bad),
        "unresolved": len(unresolved),
        "problemCounts": dict(
            Counter(r.get("geminiProblem") for r in still_bad if r.get("geminiProblem"))
        ),
        "passedSampleJudged": len(passed_judged),
        "passedSampleDefects": len(false_negatives),
        "applied": apply_verdicts,
    }
    payload.setdefault("summary", {})["adjudication"] = summary
    payload["assets"] = sorted(assets.values(), key=lambda r: r["assetId"])
    temporary = report_path.with_suffix(".json.part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    os.replace(temporary, report_path)
    return summary


# ---------------------------------------------------------------- 검사 실행


def load_report(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {item["assetId"]: item for item in payload.get("assets", [])}


def write_report(path: Path, outcomes: Mapping[str, AssetOutcome], summary: dict) -> None:
    payload = {
        "schemaVersion": 1,
        "summary": summary,
        "assets": [
            {
                "assetId": outcome.asset_id,
                "text": outcome.text,
                "kind": outcome.kind,
                "accentLocale": outcome.accent_locale,
                "passed": outcome.passed,
                "attempts": outcome.attempts,
                "firstReason": outcome.first_reason,
                "lastReason": outcome.last_reason,
                "lastTranscript": outcome.last_transcript,
                "lastRmsDbfs": outcome.last_rms_dbfs,
                "audioSha256": outcome.audio_sha256,
            }
            for outcome in sorted(outcomes.values(), key=lambda item: item.asset_id)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".json.part")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    os.replace(temporary_path, path)


def summarize(outcomes: Mapping[str, AssetOutcome]) -> dict:
    values = list(outcomes.values())
    passed_first = sum(1 for o in values if o.passed and o.attempts == 1)
    passed_retry = sum(1 for o in values if o.passed and o.attempts > 1)
    failed = [o for o in values if not o.passed]
    by_locale = Counter(o.accent_locale for o in failed)
    first_reasons = Counter(
        o.first_reason.split(" rms=", 1)[0].split(":", 1)[0]
        for o in values
        if o.first_reason
    )
    return {
        "total": len(values),
        "passedFirstTry": passed_first,
        "passedAfterResynth": passed_retry,
        "failed": len(failed),
        "failedByLocale": dict(by_locale),
        "firstTryDefectRate": round((len(values) - passed_first) / len(values), 4)
        if values
        else 0.0,
        "firstReasons": dict(first_reasons),
    }


def systematic_failures(outcomes: Mapping[str, AssetOutcome]) -> list[dict]:
    """같은 보이스가 같은 텍스트를 반복해서 같은 식으로 틀리면 계통적 실패다."""
    groups: dict[tuple[str, str, str], int] = defaultdict(int)
    for outcome in outcomes.values():
        if outcome.passed or not outcome.last_transcript:
            continue
        key = (outcome.accent_locale, outcome.text.lower(), outcome.last_transcript.lower())
        groups[key] += 1
    return [
        {"accentLocale": locale, "text": text, "heard": heard, "count": count}
        for (locale, text, heard), count in sorted(groups.items(), key=lambda kv: -kv[1])
        if count >= SYSTEMATIC_FAILURE_THRESHOLD
    ]


def _outcome_from_cached(asset: epa.SourceAsset, cached: dict) -> AssetOutcome:
    return AssetOutcome(
        asset_id=cached["assetId"],
        text=asset.text,
        kind=asset.kind,
        accent_locale=asset.accent_locale,
        passed=cached["passed"],
        attempts=cached["attempts"],
        first_reason=cached["firstReason"],
        last_reason=cached.get("lastReason", ""),
        last_transcript=cached["lastTranscript"],
        last_rms_dbfs=cached["lastRmsDbfs"],
        audio_sha256=cached["audioSha256"],
    )


def run_check(
    snapshot: epa.SourceSnapshot,
    work_dir: Path,
    report_path: Path,
    *,
    transcribe: Callable[[Path], str] | None,
    client: epa.OpenRouterSpeechClient | None,
    max_resynth: int,
    workers: int,
    ids: set[int] | None = None,
    kinds: set[str] | None = None,
    silence_only_kinds: set[str] = frozenset(),
    only_report_failures: bool = False,
    asset_ids: set[str] | None = None,
    decoder: Callable[[Path], array.array] = decode_pcm16k,
    probe_runner: Callable = subprocess.run,
    probe_name: str | None = None,
    keep_failed_dir: Path | None = None,
    keep_failed_max: int = DEFAULT_KEEP_FAILED_MAX,
    progress: Callable[[str], None] = print,
) -> dict[str, AssetOutcome]:
    state_path = work_dir / "state.json"
    state = epa.load_generation_state(state_path)
    previous = load_report(report_path)
    outcomes: dict[str, AssetOutcome] = {}
    pending: list[epa.SourceAsset] = []
    for asset in snapshot.assets:
        if ids is not None and asset.expression_id not in ids:
            continue
        if kinds is not None and asset.kind not in kinds:
            continue
        key = epa.asset_id(asset)
        generated = state.get(key)
        cached = previous.get(key)
        if asset_ids is not None and key not in asset_ids:
            if cached is not None:
                outcomes[key] = _outcome_from_cached(asset, cached)
            continue
        if only_report_failures and (cached is None or cached["passed"]):
            # 이전 보고서에서 불합격으로 확정된 자산만 다시 본다. 합격 기록은 보고서에
            # 그대로 남기고(덮어쓰지 않게 outcomes에 옮김), 아직 안 본 자산은 건너뛴다.
            if cached is not None:
                outcomes[key] = _outcome_from_cached(asset, cached)
            continue
        if generated is None:
            raise RuntimeError(f"{key}: state.json에 없다 — generate를 먼저 끝내라")
        # 같은 파일(sha 일치)을 이미 합격시켰으면 다시 전사하지 않는다.
        if cached and cached["passed"] and cached["audioSha256"] == generated.audio_sha256:
            outcomes[key] = _outcome_from_cached(asset, cached)
            continue
        pending.append(asset)

    lock = threading.Lock()
    done = 0
    started = time.monotonic()

    def check_one(asset: epa.SourceAsset) -> AssetOutcome:
        key = epa.asset_id(asset)
        path = epa.audio_path_for(work_dir, asset)
        attempts = 0
        first_reason = ""
        result = CheckResult(False, -math.inf, "", "not checked")
        while True:
            attempts += 1
            checker = None if asset.kind in silence_only_kinds else transcribe
            result = check_audio(
                path,
                asset.text,
                checker,
                decoder=decoder,
                single_word_lenient=asset.kind == epa.KIND_WORD,
                accent_locale=asset.accent_locale,
            )
            if attempts == 1:
                first_reason = result.reason
            if result.passed or client is None or attempts > max_resynth:
                break
            # 무음은 마침표 변형이 오히려 무음을 부르므로 쉼표 변형으로만 재시도한다.
            if is_function_word(asset) or result.reason.startswith("silence"):
                suffix = SILENCE_RETRY_SUFFIX
            else:
                suffix = None
            regenerated = resynthesize(
                asset,
                attempts - 1,
                work_dir,
                client,
                probe_runner=probe_runner,
                probe_name=probe_name,
                keep_failed_dir=keep_failed_dir,
                keep_failed_max=keep_failed_max,
                suffix=suffix,
            )
            with lock:
                state[key] = regenerated
        with lock:
            sha = state[key].audio_sha256
        return AssetOutcome(
            asset_id=key,
            text=asset.text,
            kind=asset.kind,
            accent_locale=asset.accent_locale,
            passed=result.passed,
            attempts=attempts,
            first_reason=first_reason,
            last_reason=result.reason,
            last_transcript=result.transcript,
            last_rms_dbfs=result.rms_dbfs,
            audio_sha256=sha,
        )

    def flush() -> None:
        with lock:
            epa.write_generation_state(state_path, state)
            write_report(report_path, outcomes, summarize(outcomes))

    cached_count = len(outcomes)
    # 검사 대기 중인 자산도 이전 판정을 자리 표시로 넣어 둔다. 중간 저장(flush)은 outcomes를
    # 통째로 쓰므로, 이게 없으면 아직 검사하지 않은 자산이 보고서에서 빠진 채 저장되고 도중에
    # 멈추면 영영 사라진다 (LAN-471 실측: 재검사를 중단하자 불합격 16건이 보고서에서 사라져
    # 다음 재검사 대상에서도 빠졌다). 검사가 끝나면 새 결과로 덮인다.
    for asset in pending:
        cached = previous.get(epa.asset_id(asset))
        if cached is not None:
            outcomes[epa.asset_id(asset)] = _outcome_from_cached(asset, cached)
    progress(f"checking {len(pending)} assets ({cached_count} cached as passed)")
    last_flush = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [executor.submit(check_one, asset) for asset in pending]
        for future in as_completed(futures):
            outcome = future.result()
            with lock:
                outcomes[outcome.asset_id] = outcome
                done += 1
            if time.monotonic() - last_flush >= 10:
                flush()
                last_flush = time.monotonic()
                elapsed = time.monotonic() - started
                failed = sum(1 for o in outcomes.values() if not o.passed)
                progress(
                    f"  {done}/{len(pending)} checked, {failed} failed, "
                    f"{done / elapsed:.1f}/s"
                )
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        flush()
        raise
    executor.shutdown(wait=True)
    flush()
    return outcomes


# ---------------------------------------------------------------- 무작위 샘플


def pick_samples(
    snapshot: epa.SourceSnapshot,
    count: int,
    seed: int,
    ids: set[int] | None = None,
) -> list[epa.SourceAsset]:
    """억양별로 같은 수를, 억양 안에서는 종류(표현·문장·단어)를 고루 섞어 뽑는다."""
    rng = random.Random(seed)
    by_locale: dict[str, list[epa.SourceAsset]] = defaultdict(list)
    for asset in snapshot.assets:
        if ids is None or asset.expression_id in ids:
            by_locale[asset.accent_locale].append(asset)
    locales = sorted(by_locale)
    per_locale = max(1, count // len(locales))
    chosen: list[epa.SourceAsset] = []
    for locale in locales:
        by_kind: dict[str, list[epa.SourceAsset]] = defaultdict(list)
        for asset in by_locale[locale]:
            by_kind[asset.kind].append(asset)
        kinds = sorted(by_kind)
        for index in range(per_locale):
            pool = by_kind[kinds[index % len(kinds)]]
            chosen.append(pool.pop(rng.randrange(len(pool))))
    return chosen


def write_samples(
    samples: list[epa.SourceAsset],
    work_dir: Path,
    out_dir: Path,
    report: Mapping[str, dict],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for asset in samples:
        key = epa.asset_id(asset)
        source = epa.audio_path_for(work_dir, asset)
        name = key.replace("/", "-") + ".mp3"
        shutil.copyfile(source, out_dir / name)
        qa = report.get(key, {})
        rows.append(
            "<tr><td>{locale}</td><td>{kind}</td><td>{text}</td>"
            "<td><audio controls preload='none' src='{file}'></audio></td>"
            "<td>{transcript}</td><td>{attempts}</td>"
            "<td><input type='checkbox' data-key='{key}'></td></tr>".format(
                locale=asset.accent_locale,
                kind=asset.kind,
                text=html.escape(asset.text),
                file=html.escape(name),
                transcript=html.escape(qa.get("lastTranscript", "")),
                attempts=qa.get("attempts", ""),
                key=html.escape(key),
            )
        )
    page = (
        "<!doctype html><meta charset='utf-8'><title>발음 자산 샘플 검수</title>"
        "<style>body{font-family:sans-serif;padding:16px}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:6px 10px;font-size:14px}</style>"
        f"<h2>발음 자산 무작위 샘플 {len(samples)}개</h2>"
        "<p>들어 보고 불량이면 오른쪽 체크박스를 켠 뒤 아래 버튼으로 목록을 복사한다.</p>"
        "<table><tr><th>억양</th><th>종류</th><th>기대 텍스트</th><th>재생</th>"
        "<th>Whisper 전사</th><th>시도</th><th>불량</th></tr>"
        + "".join(rows)
        + "</table><p><button onclick=\"navigator.clipboard.writeText("
        "[...document.querySelectorAll('input:checked')].map(e=>e.dataset.key).join('\\n'))\">"
        "불량 목록 복사</button></p>"
    )
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


# ---------------------------------------------------------------- CLI


def _parse_kinds(value: str | None) -> set[str] | None:
    if not value:
        return None
    kinds = {item.strip() for item in value.split(",") if item.strip()}
    unknown = kinds - {epa.KIND_EXPRESSION, epa.KIND_SENTENCE, epa.KIND_WORD}
    if unknown:
        raise SystemExit(f"unknown kinds: {sorted(unknown)}")
    return kinds


def _parse_ids(value: str | None) -> set[int] | None:
    if not value:
        return None
    return {int(item) for item in value.split(",") if item.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LAN-453 발음 자산 TTS 품질 검사")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("--source", required=True, type=Path)
    check.add_argument("--work-dir", required=True, type=Path)
    check.add_argument("--report", required=True, type=Path)
    check.add_argument("--resynth", action="store_true", help="불합격을 재합성한다")
    check.add_argument("--max-resynth", type=int, default=DEFAULT_MAX_RESYNTH)
    check.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    check.add_argument("--model", default=DEFAULT_WHISPER_MODEL)
    check.add_argument(
        "--backend",
        choices=("auto", "mlx", "faster"),
        default="auto",
        help="auto는 mlx-whisper가 있으면 mlx, 없으면 faster-whisper",
    )
    check.add_argument("--ids", help="쉼표 구분 expressionId 부분집합")
    check.add_argument(
        "--kinds",
        help="검사할 종류 부분집합 (expression,sentence,word). 기본은 전부",
    )
    check.add_argument(
        "--asset-ids-file",
        type=Path,
        help="한 줄에 하나씩 적힌 자산 id(예: 1005/EN_AU/word-4)만 검사한다. 나머지는 보고서 그대로",
    )
    check.add_argument(
        "--keep-failed-dir",
        type=Path,
        help="재합성으로 덮어쓰기 전의 불합격 파일을 보관할 폴더",
    )
    check.add_argument(
        "--keep-failed-max",
        type=int,
        default=DEFAULT_KEEP_FAILED_MAX,
        help="보관할 불합격 원본 개수 상한",
    )
    check.add_argument(
        "--only-report-failures",
        action="store_true",
        help="--report에 불합격으로 남은 자산만 다시 검사·재합성한다",
    )
    check.add_argument(
        "--silence-only-kinds",
        default="",
        help="이 종류는 무음 검사만 한다 (예: word). 전사 오탐이 많은 단어 클립용",
    )

    check.add_argument(
        "--transcribe-timeout",
        type=float,
        default=DEFAULT_TRANSCRIBE_TIMEOUT_SECONDS,
        help="클립 하나의 전사 제한 시간(초). 넘기면 전사 프로세스를 죽이고 불합격 처리",
    )

    worker = subparsers.add_parser("transcribe-worker", help="내부용: 전사 자식 프로세스")
    worker.add_argument("--backend", choices=("auto", "mlx", "faster"), default="auto")
    worker.add_argument("--model", default=DEFAULT_WHISPER_MODEL)

    adjudicate = subparsers.add_parser(
        "adjudicate", help="불합격 클립을 오디오 판정 모델에 다시 물어 사람 청취 대상을 좁힌다"
    )
    adjudicate.add_argument("--source", required=True, type=Path)
    adjudicate.add_argument("--work-dir", required=True, type=Path)
    adjudicate.add_argument("--report", required=True, type=Path)
    adjudicate.add_argument("--workers", type=int, default=DEFAULT_ADJUDICATION_WORKERS)
    adjudicate.add_argument(
        "--sample-passed",
        type=int,
        default=0,
        help="합격 자산 중 이 수만큼도 함께 물어 오탐(놓친 불량) 비율을 잰다",
    )
    adjudicate.add_argument("--seed", type=int, default=20260910)
    adjudicate.add_argument(
        "--apply",
        action="store_true",
        help="모델이 정상이라고 한 불합격 자산을 합격으로 반영한다 (기본은 기록만)",
    )

    sample = subparsers.add_parser("sample")
    sample.add_argument("--source", required=True, type=Path)
    sample.add_argument("--work-dir", required=True, type=Path)
    sample.add_argument("--report", required=True, type=Path)
    sample.add_argument("--out-dir", required=True, type=Path)
    sample.add_argument("--count", type=int, default=45)
    sample.add_argument("--seed", type=int, default=20260906)
    sample.add_argument("--ids", help="쉼표 구분 expressionId 부분집합")

    args = parser.parse_args(argv)
    if args.command == "transcribe-worker":
        return run_transcribe_worker(args.backend, args.model)
    snapshot = epa.load_source(args.source)

    if args.command == "check":
        client = None
        if args.resynth:
            client = epa.OpenRouterSpeechClient(os.environ["OPENROUTER_API_KEY"])
        kinds = _parse_kinds(args.kinds)
        silence_only = _parse_kinds(args.silence_only_kinds) or set()
        needs_whisper = (kinds or {epa.KIND_EXPRESSION, epa.KIND_SENTENCE, epa.KIND_WORD}) - silence_only
        transcriber = (
            build_transcriber(
                args.backend,
                args.model,
                args.workers,
                timeout_seconds=args.transcribe_timeout,
            )
            if needs_whisper
            else None
        )
        outcomes = run_check(
            snapshot,
            args.work_dir,
            args.report,
            transcribe=transcriber,
            client=client,
            max_resynth=args.max_resynth,
            workers=args.workers,
            ids=_parse_ids(args.ids),
            kinds=kinds,
            silence_only_kinds=silence_only,
            only_report_failures=args.only_report_failures,
            asset_ids=(
                {line.strip() for line in args.asset_ids_file.read_text().splitlines() if line.strip()}
                if args.asset_ids_file
                else None
            ),
            keep_failed_dir=args.keep_failed_dir,
            keep_failed_max=args.keep_failed_max,
        )
        summary = summarize(outcomes)
        if isinstance(transcriber, SubprocessTranscriber):
            summary["transcribeTimeouts"] = transcriber.timeouts
            transcriber.close()
        print(json.dumps(summary, ensure_ascii=False))
        patterns = systematic_failures(outcomes)
        if patterns:
            print(f"systematic failures (>= {SYSTEMATIC_FAILURE_THRESHOLD} repeats):")
            for item in patterns:
                print(
                    f"  {item['accentLocale']} {item['text']!r} -> {item['heard']!r} "
                    f"x{item['count']}"
                )
        print(
            "NOTE: 비언어 잡음 꼬리는 자동검사로 못 잡는다. "
            "sample 명령으로 무작위 청취를 거친 뒤 업로드할 것."
        )
        return 0 if summary["failed"] == 0 else 2

    if args.command == "adjudicate":
        summary = run_adjudication(
            args.report,
            args.work_dir,
            snapshot,
            os.environ["OPENROUTER_API_KEY"],
            workers=args.workers,
            sample_passed=args.sample_passed,
            seed=args.seed,
            apply_verdicts=args.apply,
        )
        print(json.dumps(summary, ensure_ascii=False))
        if not summary["applied"] and summary["geminiSaysClean"]:
            print(
                f"NOTE: 불합격 {summary['geminiSaysClean']}건을 모델이 정상으로 봤다. "
                "반영하려면 --apply로 다시 실행할 것."
            )
        if summary["passedSampleDefects"]:
            print(
                f"WARNING: 합격 표본 {summary['passedSampleJudged']}건 중 "
                f"{summary['passedSampleDefects']}건을 모델이 불량으로 봤다 — "
                "자동 검사가 놓치는 유형이 있다는 뜻이다."
            )
        return 0

    samples = pick_samples(snapshot, args.count, args.seed, _parse_ids(args.ids))
    index = write_samples(samples, args.work_dir, args.out_dir, load_report(args.report))
    print(f"samples={len(samples)}, index={index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
