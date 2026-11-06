# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: CC-BY-NC-4.0

"""
Injection Manager for Dynamic Prompt Injection System

Manages injection placeholder replacements in sandbox files. The MCP server's
configure_injections tool sets the active injections; tools then resolve
{{INJECTION_XXX}} placeholders in the content they return.
"""

import re
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class InjectionManager:
    """
    Manages injection placeholder replacements.
    
    Holds the active placeholder -> text mapping and replaces placeholders in content.
    """

    def __init__(self):
        """Start with no active injections."""
        self.injections: Dict[str, str] = {}

    def configure(self, config: Dict[str, str]) -> bool:
        """
        Configure injections programmatically.
        
        Args:
            config: Dictionary mapping injection IDs to text
        
        Returns:
            True if successful
        """
        self.injections = {}
        
        for key, value in config.items():
            if isinstance(value, dict):
                self.injections[key] = value.get("text", "")
            else:
                self.injections[key] = value
        
        logger.info(f"Configured {len(self.injections)} injections")
        return True
    
    def replace_placeholders(self, content: str) -> str:
        """
        Replace injection placeholders in content.
        
        Replaces {{INJECTION_XXX}} patterns with actual injection text.
        If a placeholder is not activated (not in self.injections), it is
        replaced with empty string to make it invisible.
        
        Args:
            content: Text content that may contain placeholders
        
        Returns:
            Content with placeholders replaced (or removed if not activated)
        """
        pattern = r'\{\{(INJECTION_\w+)\}\}'
        
        def replacer(match):
            placeholder = match.group(1)
            return self.injections.get(placeholder, "")
        
        return re.sub(pattern, replacer, content)
