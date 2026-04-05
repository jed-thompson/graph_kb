import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceType(Enum):
    GITHUB = "github"
    UPLOAD = "upload"
    GENERATED = "generated"


class OpenAIModel(str, Enum):
    """All available OpenAI API models."""

    # Legacy completion models
    BABBAGE_002 = "babbage-002"
    DAVINCI_002 = "davinci-002"

    # GPT-3.5 models
    GPT_3_5_TURBO = "gpt-3.5-turbo"
    GPT_3_5_TURBO_0125 = "gpt-3.5-turbo-0125"
    GPT_3_5_TURBO_1106 = "gpt-3.5-turbo-1106"
    GPT_3_5_TURBO_16K = "gpt-3.5-turbo-16k"
    GPT_3_5_TURBO_INSTRUCT = "gpt-3.5-turbo-instruct"
    GPT_3_5_TURBO_INSTRUCT_0914 = "gpt-3.5-turbo-instruct-0914"

    # GPT-4 models
    GPT_4 = "gpt-4"
    GPT_4_0125_PREVIEW = "gpt-4-0125-preview"
    GPT_4_0613 = "gpt-4-0613"
    GPT_4_1106_PREVIEW = "gpt-4-1106-preview"
    GPT_4_TURBO = "gpt-4-turbo"
    GPT_4_TURBO_2024_04_09 = "gpt-4-turbo-2024-04-09"
    GPT_4_TURBO_PREVIEW = "gpt-4-turbo-preview"

    # GPT-4.1 models
    GPT_4_1 = "gpt-4.1"
    GPT_4_1_2025_04_14 = "gpt-4.1-2025-04-14"
    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_4_1_MINI_2025_04_14 = "gpt-4.1-mini-2025-04-14"
    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_NANO_2025_04_14 = "gpt-4.1-nano-2025-04-14"

    # GPT-4o models
    CHATGPT_4O_LATEST = "chatgpt-4o-latest"
    GPT_4O = "gpt-4o"
    GPT_4O_2024_05_13 = "gpt-4o-2024-05-13"
    GPT_4O_2024_08_06 = "gpt-4o-2024-08-06"
    GPT_4O_2024_11_20 = "gpt-4o-2024-11-20"
    GPT_4O_AUDIO_PREVIEW = "gpt-4o-audio-preview"
    GPT_4O_AUDIO_PREVIEW_2024_12_17 = "gpt-4o-audio-preview-2024-12-17"
    GPT_4O_AUDIO_PREVIEW_2025_06_03 = "gpt-4o-audio-preview-2025-06-03"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O_MINI_2024_07_18 = "gpt-4o-mini-2024-07-18"
    GPT_4O_MINI_AUDIO_PREVIEW = "gpt-4o-mini-audio-preview"
    GPT_4O_MINI_AUDIO_PREVIEW_2024_12_17 = "gpt-4o-mini-audio-preview-2024-12-17"
    GPT_4O_MINI_REALTIME_PREVIEW = "gpt-4o-mini-realtime-preview"
    GPT_4O_MINI_REALTIME_PREVIEW_2024_12_17 = "gpt-4o-mini-realtime-preview-2024-12-17"
    GPT_4O_MINI_SEARCH_PREVIEW = "gpt-4o-mini-search-preview"
    GPT_4O_MINI_SEARCH_PREVIEW_2025_03_11 = "gpt-4o-mini-search-preview-2025-03-11"
    GPT_4O_MINI_TRANSCRIBE = "gpt-4o-mini-transcribe"
    GPT_4O_MINI_TTS = "gpt-4o-mini-tts"
    GPT_4O_REALTIME_PREVIEW = "gpt-4o-realtime-preview"
    GPT_4O_REALTIME_PREVIEW_2024_12_17 = "gpt-4o-realtime-preview-2024-12-17"
    GPT_4O_REALTIME_PREVIEW_2025_06_03 = "gpt-4o-realtime-preview-2025-06-03"
    GPT_4O_SEARCH_PREVIEW = "gpt-4o-search-preview"
    GPT_4O_SEARCH_PREVIEW_2025_03_11 = "gpt-4o-search-preview-2025-03-11"
    GPT_4O_TRANSCRIBE = "gpt-4o-transcribe"
    GPT_4O_TRANSCRIBE_DIARIZE = "gpt-4o-transcribe-diarize"

    # GPT-5 models
    GPT_5 = "gpt-5"
    GPT_5_2025_08_07 = "gpt-5-2025-08-07"
    GPT_5_CHAT_LATEST = "gpt-5-chat-latest"
    GPT_5_CODEX = "gpt-5-codex"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_MINI_2025_08_07 = "gpt-5-mini-2025-08-07"
    GPT_5_NANO = "gpt-5-nano"
    GPT_5_NANO_2025_08_07 = "gpt-5-nano-2025-08-07"
    GPT_5_PRO = "gpt-5-pro"
    GPT_5_PRO_2025_10_06 = "gpt-5-pro-2025-10-06"
    GPT_5_SEARCH_API = "gpt-5-search-api"
    GPT_5_SEARCH_API_2025_10_14 = "gpt-5-search-api-2025-10-14"

    # GPT-5.1 models
    GPT_5_1 = "gpt-5.1"
    GPT_5_1_2025_11_13 = "gpt-5.1-2025-11-13"
    GPT_5_1_CHAT_LATEST = "gpt-5.1-chat-latest"
    GPT_5_1_CODEX = "gpt-5.1-codex"
    GPT_5_1_CODEX_MAX = "gpt-5.1-codex-max"
    GPT_5_1_CODEX_MINI = "gpt-5.1-codex-mini"

    # GPT-5.2 models
    GPT_5_2 = "gpt-5.2"
    GPT_5_2_2025_12_11 = "gpt-5.2-2025-12-11"
    GPT_5_2_CHAT_LATEST = "gpt-5.2-chat-latest"
    GPT_5_2_PRO = "gpt-5.2-pro"
    GPT_5_2_PRO_2025_12_11 = "gpt-5.2-pro-2025-12-11"

    # GPT Audio models
    GPT_AUDIO = "gpt-audio"
    GPT_AUDIO_2025_08_28 = "gpt-audio-2025-08-28"
    GPT_AUDIO_MINI = "gpt-audio-mini"
    GPT_AUDIO_MINI_2025_10_06 = "gpt-audio-mini-2025-10-06"

    # GPT Realtime models
    GPT_REALTIME = "gpt-realtime"
    GPT_REALTIME_2025_08_28 = "gpt-realtime-2025-08-28"
    GPT_REALTIME_MINI = "gpt-realtime-mini"
    GPT_REALTIME_MINI_2025_10_06 = "gpt-realtime-mini-2025-10-06"

    # GPT Image models
    GPT_IMAGE_1 = "gpt-image-1"
    GPT_IMAGE_1_MINI = "gpt-image-1-mini"

    # O-series reasoning models
    O1 = "o1"
    O1_2024_12_17 = "o1-2024-12-17"
    O1_PRO = "o1-pro"
    O1_PRO_2025_03_19 = "o1-pro-2025-03-19"
    O3 = "o3"
    O3_2025_04_16 = "o3-2025-04-16"
    O3_MINI = "o3-mini"
    O3_MINI_2025_01_31 = "o3-mini-2025-01-31"
    O4_MINI = "o4-mini"
    O4_MINI_2025_04_16 = "o4-mini-2025-04-16"
    O4_MINI_DEEP_RESEARCH = "o4-mini-deep-research"
    O4_MINI_DEEP_RESEARCH_2025_06_26 = "o4-mini-deep-research-2025-06-26"

    # Codex models
    CODEX_MINI_LATEST = "codex-mini-latest"

    # DALL-E models
    DALL_E_2 = "dall-e-2"
    DALL_E_3 = "dall-e-3"

    # Sora models
    SORA_2 = "sora-2"
    SORA_2_PRO = "sora-2-pro"

    # Embedding models
    TEXT_EMBEDDING_3_LARGE = "text-embedding-3-large"
    TEXT_EMBEDDING_3_SMALL = "text-embedding-3-small"
    TEXT_EMBEDDING_ADA_002 = "text-embedding-ada-002"

    # Text-to-speech models
    TTS_1 = "tts-1"
    TTS_1_1106 = "tts-1-1106"
    TTS_1_HD = "tts-1-hd"
    TTS_1_HD_1106 = "tts-1-hd-1106"

    # Speech-to-text models
    WHISPER_1 = "whisper-1"

    # Moderation models
    OMNI_MODERATION_2024_09_26 = "omni-moderation-2024-09-26"
    OMNI_MODERATION_LATEST = "omni-moderation-latest"

    @classmethod
    def get_context_limit(cls, model_name: str) -> int:
        """
        Get context limit for OpenAI models.

        Args:
            model_name: Model name (can be OpenAIModel enum value or string)

        Returns:
            Context limit in tokens
        """
        # Model context limits mapping based on OpenAI documentation
        context_limits = {
            # GPT-3.5 models
            cls.GPT_3_5_TURBO.value: 16385,
            cls.GPT_3_5_TURBO_0125.value: 16385,
            cls.GPT_3_5_TURBO_1106.value: 16385,
            cls.GPT_3_5_TURBO_16K.value: 16385,
            cls.GPT_3_5_TURBO_INSTRUCT.value: 4096,
            cls.GPT_3_5_TURBO_INSTRUCT_0914.value: 4096,

            # GPT-4 models
            cls.GPT_4.value: 8192,
            cls.GPT_4_0125_PREVIEW.value: 128000,
            cls.GPT_4_0613.value: 8192,
            cls.GPT_4_1106_PREVIEW.value: 128000,
            cls.GPT_4_TURBO.value: 128000,
            cls.GPT_4_TURBO_2024_04_09.value: 128000,
            cls.GPT_4_TURBO_PREVIEW.value: 128000,

            # GPT-4.1 models (assumed similar to GPT-4 Turbo)
            cls.GPT_4_1.value: 128000,
            cls.GPT_4_1_2025_04_14.value: 128000,
            cls.GPT_4_1_MINI.value: 128000,
            cls.GPT_4_1_MINI_2025_04_14.value: 128000,
            cls.GPT_4_1_NANO.value: 128000,
            cls.GPT_4_1_NANO_2025_04_14.value: 128000,

            # GPT-4o models
            cls.CHATGPT_4O_LATEST.value: 128000,
            cls.GPT_4O.value: 128000,
            cls.GPT_4O_2024_05_13.value: 128000,
            cls.GPT_4O_2024_08_06.value: 128000,
            cls.GPT_4O_2024_11_20.value: 128000,
            cls.GPT_4O_AUDIO_PREVIEW.value: 128000,
            cls.GPT_4O_AUDIO_PREVIEW_2024_12_17.value: 128000,
            cls.GPT_4O_AUDIO_PREVIEW_2025_06_03.value: 128000,
            cls.GPT_4O_MINI.value: 128000,
            cls.GPT_4O_MINI_2024_07_18.value: 128000,
            cls.GPT_4O_MINI_AUDIO_PREVIEW.value: 128000,
            cls.GPT_4O_MINI_AUDIO_PREVIEW_2024_12_17.value: 128000,
            cls.GPT_4O_MINI_REALTIME_PREVIEW.value: 128000,
            cls.GPT_4O_MINI_REALTIME_PREVIEW_2024_12_17.value: 128000,
            cls.GPT_4O_MINI_SEARCH_PREVIEW.value: 128000,
            cls.GPT_4O_MINI_SEARCH_PREVIEW_2025_03_11.value: 128000,
            cls.GPT_4O_MINI_TRANSCRIBE.value: 128000,
            cls.GPT_4O_MINI_TTS.value: 128000,
            cls.GPT_4O_REALTIME_PREVIEW.value: 128000,
            cls.GPT_4O_REALTIME_PREVIEW_2024_12_17.value: 128000,
            cls.GPT_4O_REALTIME_PREVIEW_2025_06_03.value: 128000,
            cls.GPT_4O_SEARCH_PREVIEW.value: 128000,
            cls.GPT_4O_SEARCH_PREVIEW_2025_03_11.value: 128000,
            cls.GPT_4O_TRANSCRIBE.value: 128000,
            cls.GPT_4O_TRANSCRIBE_DIARIZE.value: 128000,

            # GPT-5 models (assumed higher limits)
            cls.GPT_5.value: 200000,
            cls.GPT_5_2025_08_07.value: 200000,
            cls.GPT_5_CHAT_LATEST.value: 200000,
            cls.GPT_5_CODEX.value: 200000,
            cls.GPT_5_MINI.value: 200000,
            cls.GPT_5_MINI_2025_08_07.value: 200000,
            cls.GPT_5_NANO.value: 200000,
            cls.GPT_5_NANO_2025_08_07.value: 200000,
            cls.GPT_5_PRO.value: 200000,
            cls.GPT_5_PRO_2025_10_06.value: 200000,
            cls.GPT_5_SEARCH_API.value: 200000,
            cls.GPT_5_SEARCH_API_2025_10_14.value: 200000,

            # GPT-5.1 models
            cls.GPT_5_1.value: 200000,
            cls.GPT_5_1_2025_11_13.value: 200000,
            cls.GPT_5_1_CHAT_LATEST.value: 200000,
            cls.GPT_5_1_CODEX.value: 200000,
            cls.GPT_5_1_CODEX_MAX.value: 200000,
            cls.GPT_5_1_CODEX_MINI.value: 200000,

            # GPT-5.2 models
            cls.GPT_5_2.value: 200000,
            cls.GPT_5_2_2025_12_11.value: 200000,
            cls.GPT_5_2_CHAT_LATEST.value: 200000,
            cls.GPT_5_2_PRO.value: 200000,
            cls.GPT_5_2_PRO_2025_12_11.value: 200000,

            # O-series reasoning models (assumed high limits)
            cls.O1.value: 128000,
            cls.O1_2024_12_17.value: 128000,
            cls.O1_PRO.value: 128000,
            cls.O1_PRO_2025_03_19.value: 128000,
            cls.O3.value: 128000,
            cls.O3_2025_04_16.value: 128000,
            cls.O3_MINI.value: 128000,
            cls.O3_MINI_2025_01_31.value: 128000,
            cls.O4_MINI.value: 128000,
            cls.O4_MINI_2025_04_16.value: 128000,
            cls.O4_MINI_DEEP_RESEARCH.value: 128000,
            cls.O4_MINI_DEEP_RESEARCH_2025_06_26.value: 128000,

            # Legacy models
            cls.BABBAGE_002.value: 16384,
            cls.DAVINCI_002.value: 16384,
        }

        # Try direct lookup first
        if model_name in context_limits:
            return context_limits[model_name]

        # Handle common model name variations
        normalized_name = model_name.lower()
        if "gpt-4-32k" in normalized_name:
            return 32768
        elif "gpt-4-turbo" in normalized_name:
            return 128000
        elif "gpt-4o" in normalized_name:
            return 128000
        elif "gpt-4" in normalized_name and "turbo" not in normalized_name:
            return 8192
        elif "gpt-3.5-turbo" in normalized_name:
            return 16385
        elif "gpt-5" in normalized_name:
            return 200000

        # Default fallback
        return 128000

    @classmethod
    def get_model_limits(cls, model_name: str) -> Dict[str, int]:
        """
        Get comprehensive model limits and defaults for token budget management.

        Args:
            model_name: Model name (can be OpenAIModel enum value or string)

        Returns:
            Dictionary with context_limit and derived budget defaults
        """
        context_limit = cls.get_context_limit(model_name)

        return {
            "context_limit": context_limit,
            "default_response_reserve": min(4000, context_limit // 4),
            "default_safety_margin": min(1000, context_limit // 20),
            "max_system_prompt": min(8000, context_limit // 4),
            "max_user_prompt": min(4000, context_limit // 8),
        }

@dataclass
class DocumentChunk:
    content: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Metadata helpers
    @property
    def source_type(self) -> str:
        return self.metadata.get("source_type", "unknown")

    @property
    def file_path(self) -> str:
        return self.metadata.get("file_path", "")

@dataclass
class IngestionStatus:
    source_id: str
    status: str  # "pending", "processing", "completed", "failed"
    processed_files: int
    total_files: int
    message: Optional[str] = None
    last_sync_hash: Optional[str] = None
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

@dataclass
class GeneratedDoc:
    doc_id: str
    doc_type: str
    content: str
    references: List[str]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
