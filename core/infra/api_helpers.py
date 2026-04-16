"""
API Helpers - Standardized response formats for Flask endpoints.

This module provides helper functions to create consistent API responses
across all endpoints, reducing code duplication.
"""

from flask import jsonify
from typing import Optional, Any, Dict


def success_response(
    mode: str = None,
    original: str = None,
    modified: str = None,
    generation_time: float = None,
    generation_id: str = None,
    **kwargs
) -> tuple:
    """
    Create a standardized success response for generation endpoints.

    Args:
        mode: Generation mode ('inpaint', 'txt2img', etc.)
        original: Base64 encoded original image
        modified: Base64 encoded modified image
        generation_time: Time taken for generation in seconds
        generation_id: Unique generation identifier
        **kwargs: Additional fields to include in response

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {'success': True}

    if mode is not None:
        response['mode'] = mode
    if original is not None:
        response['original'] = original
    if modified is not None:
        response['modified'] = modified
    if generation_time is not None:
        response['generationTime'] = round(generation_time, 1)
    if generation_id is not None:
        response['generationId'] = generation_id

    # Add any additional kwargs
    response.update(kwargs)

    return jsonify(response), 200


def error_response(error: str, status: int = 500, **kwargs) -> tuple:
    """
    Create a standardized error response.

    Args:
        error: Error message
        status: HTTP status code (default: 500)
        **kwargs: Additional fields to include in response

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {'success': False, 'error': str(error)}
    response.update(kwargs)
    return jsonify(response), status


def cancelled_response(error: str = 'Génération annulée') -> tuple:
    """
    Create a standardized cancellation response.

    Args:
        error: Cancellation message (default: 'Génération annulée')

    Returns:
        Tuple of (response_json, status_code)
    """
    return jsonify({
        'success': False,
        'cancelled': True,
        'error': error
    }), 200


def validation_error(message: str) -> tuple:
    """
    Create a validation error response (400 Bad Request).

    Args:
        message: Validation error message

    Returns:
        Tuple of (response_json, status_code)
    """
    return error_response(message, status=400)


def not_found_error(message: str = 'Resource not found') -> tuple:
    """
    Create a not found error response (404).

    Args:
        message: Not found message

    Returns:
        Tuple of (response_json, status_code)
    """
    return error_response(message, status=404)


def image_response(
    image_base64: str,
    status: str = None,
    generation_time: float = None,
    **kwargs
) -> tuple:
    """
    Create a response for image-only endpoints (upscale, expand).

    Args:
        image_base64: Base64 encoded image
        status: Status message
        generation_time: Time taken in seconds
        **kwargs: Additional fields

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {'success': True, 'image': image_base64}

    if status is not None:
        response['status'] = status
    if generation_time is not None:
        response['generationTime'] = round(generation_time, 1)

    response.update(kwargs)
    return jsonify(response), 200


def video_response(
    video_base64: str,
    video_format: str,
    generation_time: float = None,
    total_frames: int = None,
    total_duration: float = None,
    can_continue: bool = False,
    **kwargs
) -> tuple:
    """
    Create a response for video generation endpoint.

    Args:
        video_base64: Base64 encoded video
        video_format: Video format (mp4, webm, gif)
        generation_time: Time taken in seconds
        total_frames: Total frames in video
        total_duration: Total video duration in seconds
        can_continue: Whether generation can continue
        **kwargs: Additional fields

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {
        'success': True,
        'video': video_base64,
        'format': video_format,
        'canContinue': can_continue
    }

    if generation_time is not None:
        response['generationTime'] = round(generation_time, 1)
    if total_frames is not None:
        response['totalFrames'] = total_frames
    if total_duration is not None:
        response['totalDuration'] = round(total_duration, 1)

    response.update(kwargs)
    return jsonify(response), 200


def chat_response(
    response_text: str,
    intent: str = 'chat',
    new_memories: list = None,
    generate_image: bool = False,
    image_prompt: str = None,
    **kwargs
) -> tuple:
    """
    Create a response for chat endpoint.

    Args:
        response_text: AI response text
        intent: Response intent ('chat', 'image_generate_pending')
        new_memories: New memories extracted from conversation
        generate_image: Whether to generate an image
        image_prompt: Image generation prompt
        **kwargs: Additional fields

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {
        'success': True,
        'response': response_text,
        'intent': intent,
        'new_memories': new_memories or []
    }

    if generate_image:
        response['generate_image'] = True
        response['gen_prompt'] = image_prompt

    response.update(kwargs)
    return jsonify(response), 200


def suggestions_response(
    suggestions: list,
    content_type: str,
    description: str = None
) -> tuple:
    """
    Create a response for image suggestions endpoint.

    Args:
        suggestions: List of suggestion objects
        content_type: Detected content type ('woman', 'man', 'generic')
        description: Image description from BLIP

    Returns:
        Tuple of (response_json, status_code)
    """
    response = {
        'success': True,
        'suggestions': suggestions,
        'contentType': content_type
    }

    if description:
        response['description'] = description

    return jsonify(response), 200


class GenerationResult:
    """
    Helper class to build generation responses incrementally.
    """

    def __init__(self):
        self.data: Dict[str, Any] = {'success': True}

    def set_mode(self, mode: str) -> 'GenerationResult':
        self.data['mode'] = mode
        return self

    def set_images(self, original: str = None, modified: str = None) -> 'GenerationResult':
        if original is not None:
            self.data['original'] = original
        if modified is not None:
            self.data['modified'] = modified
        return self

    def set_timing(self, generation_time: float) -> 'GenerationResult':
        self.data['generationTime'] = round(generation_time, 1)
        return self

    def set_id(self, generation_id: str) -> 'GenerationResult':
        self.data['generationId'] = generation_id
        return self

    def set_prompt(self, prompt: str) -> 'GenerationResult':
        self.data['prompt'] = prompt
        return self

    def add(self, **kwargs) -> 'GenerationResult':
        self.data.update(kwargs)
        return self

    def to_response(self) -> tuple:
        return jsonify(self.data), 200
