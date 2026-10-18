"""Whole audio replies in memory, with an optional byte-for-byte integrity check."""
import base64
import binascii
import hashlib
import hmac

MAX_REPLY_AUDIO_BYTES = 8_000_000


def attach_audio(result: dict, audio: bytes):
    if not 0 < len(audio) <= MAX_REPLY_AUDIO_BYTES:
        raise ValueError("Reply audio is empty or exceeds 8 MB")
    result["audio_base64"] = base64.b64encode(audio).decode("ascii")
    result["audio_info"] = {"bytes": len(audio), "sha256": hashlib.sha256(audio).hexdigest()}


def reply_audio(result: dict, *, require_checksum=False) -> bytes:
    encoded = result.get("audio_base64")
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_REPLY_AUDIO_BYTES + 2) // 3):
        raise ValueError("Missing or oversized reply audio")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Reply audio is not valid base64") from error
    if not 0 < len(audio) <= MAX_REPLY_AUDIO_BYTES:
        raise ValueError("Missing or oversized reply audio")
    info = result.get("audio_info")
    if info is None:
        if require_checksum:
            raise ValueError("The server did not supply an audio checksum. Update and restart marsi-server.")
        return audio  # Compatibility with an older server during an update.
    if (not isinstance(info, dict) or type(info.get("bytes")) is not int
            or info["bytes"] != len(audio) or not isinstance(info.get("sha256"), str)
            or not info["sha256"].isascii()
            or not hmac.compare_digest(info["sha256"], hashlib.sha256(audio).hexdigest())):
        raise ValueError("Reply audio size/checksum mismatch; playback was refused")
    return audio
