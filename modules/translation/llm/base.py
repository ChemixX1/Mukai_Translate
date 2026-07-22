from typing import Any
import numpy as np
from abc import abstractmethod
import base64
import imkit as imk

from ..base import LLMTranslation
from ...utils.textblock import TextBlock
from ...utils.translator_utils import get_raw_text, set_texts_from_json


class BaseLLMTranslation(LLMTranslation):
    """Base class for LLM-based translation engines with shared functionality."""
    
    def __init__(self):
        self.source_lang = None
        self.target_lang = None
        self.api_key = None
        self.api_url = None
        self.model = None
        self.img_as_llm_input = False
        self.temperature = None
        self.top_p = None
        self.max_tokens = None
        self.timeout = 30  
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, **kwargs) -> None:
        """
        Initialize the LLM translation engine.
        
        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
            **kwargs: Engine-specific initialization parameters
        """
        llm_settings = settings.get_llm_settings()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.img_as_llm_input = llm_settings.get('image_input_enabled', True)
        self.temperature = 0.3
        self.top_p = 0.9
        self.max_tokens = 5000
        
    def translate(self, blk_list: list[TextBlock], image: np.ndarray, extra_context: str) -> list[TextBlock]:
        """
        Translate text blocks using LLM.
        
        Args:
            blk_list: List of TextBlock objects to translate
            image: Image as numpy array
            extra_context: Additional context information for translation
            
        Returns:
            List of updated TextBlock objects with translations
        """
        entire_raw_text = get_raw_text(blk_list)
        system_prompt = self.get_system_prompt(self.source_lang, self.target_lang)
        user_prompt = self._build_translation_prompt(entire_raw_text, extra_context)
        
        entire_translated_text = self._perform_translation(user_prompt, system_prompt, image)
        if not set_texts_from_json(blk_list, entire_translated_text):
            repair_prompt = self._build_repair_prompt(entire_raw_text, entire_translated_text)
            repaired_text = self._perform_translation(repair_prompt, system_prompt, image)
            if not set_texts_from_json(blk_list, repaired_text):
                raise ValueError("LLM translation response was not valid JSON with all expected block keys.")
            
        return blk_list

    def _build_translation_prompt(self, entire_raw_text: str, extra_context: str) -> str:
        context = (extra_context or "").strip()
        context_section = f"Comic/context notes:\n{context}\n\n" if context else ""
        return (
            f"{context_section}"
            "Translate the following JSON object. Return only valid JSON with the exact same keys.\n"
            "Every value must be a string.\n\n"
            f"{entire_raw_text}"
        )

    def _build_repair_prompt(self, entire_raw_text: str, previous_response: str) -> str:
        return (
            "Your previous response was not valid JSON with the exact same block keys.\n"
            "Repair it now. Return only one valid JSON object, with no markdown or explanation.\n\n"
            "Original input JSON:\n"
            f"{entire_raw_text}\n\n"
            "Previous response:\n"
            f"{(previous_response or '')[:6000]}"
        )
    
    @abstractmethod
    def _perform_translation(self, user_prompt: str, system_prompt: str, image: np.ndarray) -> str:
        """
        Perform translation using specific LLM.
        
        Args:
            user_prompt: User prompt for LLM
            system_prompt: System prompt for LLM
            image: Image as numpy array
            
        Returns:
            Translated JSON text
        """
        pass

    def encode_image(self, image: np.ndarray, ext=".jpg"):
        """
        Encode CV2/numpy image directly to base64 string using cv2.imencode.
        
        Args:
            image: Numpy array representing the image
            ext: Extension/format to encode the image as (".png" by default for higher quality)
                
        Returns:
            Tuple of (Base64 encoded string, mime_type)
        """
        # Direct encoding from numpy/cv2 format to bytes
        buffer = imk.encode_image(image, ext.lstrip('.'))
        
        # Convert to base64
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        # Map extension to mime type
        mime_types = {
            ".jpg": "image/jpeg", 
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp"
        }
        mime_type = mime_types.get(ext.lower(), f"image/{ext[1:].lower()}")
        
        return img_str, mime_type
