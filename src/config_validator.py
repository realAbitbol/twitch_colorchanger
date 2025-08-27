"""
Enhanced configuration validation for the Twitch Color Changer bot
"""

import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

from .logger import logger


@dataclass
class ValidationError:
    """Represents a configuration validation error"""
    field: str
    message: str
    severity: str = "error"  # "error", "warning", "info"


class ConfigValidator:
    """Advanced configuration validator with detailed error reporting"""
    
    # Twitch username pattern (3-25 chars, word characters)
    USERNAME_PATTERN = re.compile(r'^\w{3,25}$')
    
    # Twitch OAuth token patterns
    ACCESS_TOKEN_PATTERN = re.compile(r'^[a-z0-9]{30,}$')
    REFRESH_TOKEN_PATTERN = re.compile(r'^[a-z0-9]{50,}$')
    CLIENT_ID_PATTERN = re.compile(r'^[a-z0-9]{30}$')
    CLIENT_SECRET_PATTERN = re.compile(r'^[a-z0-9]{30}$')
    
    # Channel name pattern (same as username)
    CHANNEL_PATTERN = re.compile(r'^\w{3,25}$')
    
    @classmethod
    def validate_user_config(cls, user_config: Dict[str, Any], user_index: int = 0) -> Tuple[bool, List[ValidationError]]:
        """
        Validate a single user configuration
        
        Args:
            user_config: Dictionary containing user configuration
            user_index: Index of the user (for error reporting)
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        username = user_config.get('username', '')
        
        # Validate required fields
        errors.extend(cls._validate_required_fields(user_config, user_index))
        
        # Validate username
        errors.extend(cls._validate_username(username, user_index))
        
        # Validate tokens
        errors.extend(cls._validate_tokens(user_config, user_index))
        
        # Validate channels
        errors.extend(cls._validate_channels(user_config, user_index))
        
        # Validate boolean fields
        errors.extend(cls._validate_boolean_fields(user_config, user_index))
        
        # Check for security issues
        errors.extend(cls._validate_security(user_config, user_index))
        
        # Check for best practice recommendations
        errors.extend(cls._validate_best_practices(user_config, user_index))
        
        # Determine if configuration is valid (no errors, warnings are ok)
        is_valid = not any(error.severity == "error" for error in errors)
        
        return is_valid, errors
    
    @classmethod
    def validate_all_configs(cls, users_config: List[Dict[str, Any]]) -> Tuple[bool, List[ValidationError]]:
        """
        Validate all user configurations and check for conflicts
        
        Args:
            users_config: List of user configuration dictionaries
            
        Returns:
            Tuple of (all_valid, list_of_all_errors)
        """
        all_errors = []
        all_valid = True
        
        if not users_config:
            all_errors.append(ValidationError("users", "No user configurations provided", "error"))
            return False, all_errors
        
        # Validate each user
        for i, user_config in enumerate(users_config):
            is_valid, errors = cls.validate_user_config(user_config, i + 1)
            all_errors.extend(errors)
            if not is_valid:
                all_valid = False
        
        # Check for conflicts between users
        conflict_errors = cls._validate_user_conflicts(users_config)
        all_errors.extend(conflict_errors)
        
        if conflict_errors:
            all_valid = False
        
        return all_valid, all_errors
    
    @classmethod
    def _validate_required_fields(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Validate that all required fields are present and non-empty"""
        errors = []
        required_fields = ['username', 'access_token', 'channels']
        
        for field in required_fields:
            if not user_config.get(field):
                errors.append(ValidationError(
                    f"user_{user_index}.{field}",
                    f"Required field '{field}' is missing or empty",
                    "error"
                ))
        
        return errors
    
    @classmethod
    def _validate_username(cls, username: str, user_index: int) -> List[ValidationError]:
        """Validate Twitch username format"""
        errors = []
        
        if not username:
            return errors  # Already handled by required fields validation
        
        if not cls.USERNAME_PATTERN.match(username):
            errors.append(ValidationError(
                f"user_{user_index}.username",
                f"Username '{username}' is invalid. Must be 3-25 characters, alphanumeric + underscore only",
                "error"
            ))
        
        if username.lower() != username:
            errors.append(ValidationError(
                f"user_{user_index}.username",
                f"Username '{username}' contains uppercase letters. Twitch usernames are case-insensitive and stored in lowercase",
                "warning"
            ))
        
        return errors
    
    @classmethod
    def _validate_tokens(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Validate OAuth tokens format and completeness"""
        errors = []
        
        # Validate access token
        access_token = user_config.get('access_token', '')
        if access_token and not cls.ACCESS_TOKEN_PATTERN.match(access_token):
            errors.append(ValidationError(
                f"user_{user_index}.access_token",
                "Access token format appears invalid. Should be 30+ lowercase alphanumeric characters",
                "error"
            ))
        
        # Validate refresh token
        refresh_token = user_config.get('refresh_token', '')
        if refresh_token and not cls.REFRESH_TOKEN_PATTERN.match(refresh_token):
            errors.append(ValidationError(
                f"user_{user_index}.refresh_token",
                "Refresh token format appears invalid. Should be 50+ lowercase alphanumeric characters",
                "warning"
            ))
        
        # Validate client credentials
        client_id = user_config.get('client_id', '')
        client_secret = user_config.get('client_secret', '')
        
        if client_id and not cls.CLIENT_ID_PATTERN.match(client_id):
            errors.append(ValidationError(
                f"user_{user_index}.client_id",
                "Client ID format appears invalid. Should be exactly 30 lowercase alphanumeric characters",
                "warning"
            ))
        
        if client_secret and not cls.CLIENT_SECRET_PATTERN.match(client_secret):
            errors.append(ValidationError(
                f"user_{user_index}.client_secret",
                "Client secret format appears invalid. Should be exactly 30 lowercase alphanumeric characters",
                "warning"
            ))
        
        # Check for missing token refresh capabilities
        if not refresh_token and not (client_id and client_secret):
            errors.append(ValidationError(
                f"user_{user_index}.tokens",
                "No token refresh capability configured. Provide either refresh_token or both client_id and client_secret",
                "warning"
            ))
        
        return errors
    
    @classmethod
    def _validate_channels(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Validate channel list format and contents"""
        errors = []
        channels = user_config.get('channels', [])
        
        if not channels:
            return errors  # Already handled by required fields validation
        
        errors.extend(cls._validate_channels_type_and_count(channels, user_index))
        if isinstance(channels, list):
            errors.extend(cls._validate_individual_channels(channels, user_index))
            errors.extend(cls._validate_channel_duplicates(channels, user_index))
        
        return errors
    
    @classmethod
    def _validate_channels_type_and_count(cls, channels: Any, user_index: int) -> List[ValidationError]:
        """Validate channels type and count"""
        errors = []
        
        if not isinstance(channels, list):
            errors.append(ValidationError(
                f"user_{user_index}.channels",
                f"Channels must be a list, got {type(channels).__name__}",
                "error"
            ))
            return errors
        
        if len(channels) > 20:
            errors.append(ValidationError(
                f"user_{user_index}.channels",
                f"Too many channels ({len(channels)}). Consider limiting to 20 or fewer for better performance",
                "warning"
            ))
        
        return errors
    
    @classmethod
    def _validate_individual_channels(cls, channels: List[Any], user_index: int) -> List[ValidationError]:
        """Validate each individual channel"""
        errors = []
        
        for i, channel in enumerate(channels):
            if not isinstance(channel, str):
                errors.append(ValidationError(
                    f"user_{user_index}.channels[{i}]",
                    f"Channel name must be a string, got {type(channel).__name__}",
                    "error"
                ))
                continue
            
            if not cls.CHANNEL_PATTERN.match(channel):
                errors.append(ValidationError(
                    f"user_{user_index}.channels[{i}]",
                    f"Channel name '{channel}' is invalid. Must be 3-25 characters, alphanumeric + underscore only",
                    "error"
                ))
            
            if channel.lower() != channel:
                errors.append(ValidationError(
                    f"user_{user_index}.channels[{i}]",
                    f"Channel name '{channel}' contains uppercase letters. Twitch channels are case-insensitive and stored in lowercase",
                    "warning"
                ))
        
        return errors
    
    @classmethod
    def _validate_channel_duplicates(cls, channels: List[Any], user_index: int) -> List[ValidationError]:
        """Check for duplicate channels"""
        errors = []
        seen_channels = set()
        
        for i, channel in enumerate(channels):
            if isinstance(channel, str):
                channel_lower = channel.lower()
                if channel_lower in seen_channels:
                    errors.append(ValidationError(
                        f"user_{user_index}.channels[{i}]",
                        f"Duplicate channel '{channel}' found in list",
                        "warning"
                    ))
                seen_channels.add(channel_lower)
        
        return errors
    
    @classmethod
    def _validate_boolean_fields(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Validate boolean configuration fields"""
        errors = []
        
        use_random_colors = user_config.get('use_random_colors')
        if use_random_colors is not None and not isinstance(use_random_colors, bool):
            errors.append(ValidationError(
                f"user_{user_index}.use_random_colors",
                f"use_random_colors must be a boolean (true/false), got {type(use_random_colors).__name__}",
                "error"
            ))
        
        return errors
    
    @classmethod
    def _validate_security(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Check for potential security issues"""
        errors = []
        
        # Check for obviously fake/test tokens
        access_token = user_config.get('access_token', '')
        if access_token.lower() in ['test', 'placeholder', 'your_token_here', 'fake_token', '']:
            errors.append(ValidationError(
                f"user_{user_index}.access_token",
                "Access token appears to be a placeholder. Use a real token from https://twitchtokengenerator.com",
                "error"
            ))
        
        # Check for token exposure in logs (common patterns)
        for field in ['access_token', 'refresh_token', 'client_secret']:
            value = user_config.get(field, '')
            if value and len(value) < 10:
                errors.append(ValidationError(
                    f"user_{user_index}.{field}",
                    f"{field} is suspiciously short. This may be a truncated or invalid token",
                    "warning"
                ))
        
        return errors
    
    @classmethod
    def _validate_best_practices(cls, user_config: Dict[str, Any], user_index: int) -> List[ValidationError]:
        """Check for best practice recommendations"""
        errors = []
        
        # Recommend using refresh tokens
        if not user_config.get('refresh_token'):
            errors.append(ValidationError(
                f"user_{user_index}.refresh_token",
                "Consider adding a refresh token for automatic token renewal",
                "info"
            ))
        
        # Recommend reasonable channel limits
        channels = user_config.get('channels', [])
        if len(channels) > 10:
            errors.append(ValidationError(
                f"user_{user_index}.channels",
                f"Monitoring {len(channels)} channels may impact performance. Consider reducing the number",
                "info"
            ))
        
        # Check if user is monitoring their own channel
        username = user_config.get('username', '').lower()
        user_channels = [ch.lower() for ch in channels if isinstance(ch, str)]
        if username and username not in user_channels:
            errors.append(ValidationError(
                f"user_{user_index}.channels",
                f"Consider adding your own channel '{username}' to the channels list",
                "info"
            ))
        
        return errors
    
    @classmethod
    def _validate_user_conflicts(cls, users_config: List[Dict[str, Any]]) -> List[ValidationError]:
        """Check for conflicts between multiple users"""
        errors = []
        
        errors.extend(cls._validate_duplicate_usernames(users_config))
        errors.extend(cls._validate_overlapping_channels(users_config))
        
        return errors
    
    @classmethod
    def _validate_duplicate_usernames(cls, users_config: List[Dict[str, Any]]) -> List[ValidationError]:
        """Check for duplicate usernames"""
        errors = []
        usernames = {}
        
        for i, user_config in enumerate(users_config):
            username = user_config.get('username', '').lower()
            if username:
                if username in usernames:
                    errors.append(ValidationError(
                        f"user_{i + 1}.username",
                        f"Username '{username}' is duplicated (also used by user {usernames[username]})",
                        "error"
                    ))
                else:
                    usernames[username] = i + 1
        
        return errors
    
    @classmethod
    def _validate_overlapping_channels(cls, users_config: List[Dict[str, Any]]) -> List[ValidationError]:
        """Check for overlapping channels between users"""
        errors = []
        all_channels = {}
        
        for i, user_config in enumerate(users_config):
            username = user_config.get('username', '')
            channels = user_config.get('channels', [])
            
            for channel in channels:
                if isinstance(channel, str):
                    channel_lower = channel.lower()
                    if channel_lower in all_channels:
                        other_user = all_channels[channel_lower]
                        errors.append(ValidationError(
                            f"user_{i + 1}.channels",
                            f"Channel '{channel}' is also monitored by user {other_user}. This may cause duplicate color changes",
                            "warning"
                        ))
                    else:
                        all_channels[channel_lower] = username
        
        return errors
    
    @classmethod
    def print_validation_report(cls, errors: List[ValidationError]) -> None:
        """Print a formatted validation report"""
        if not errors:
            logger.info("✅ Configuration validation passed with no issues")
            return
        
        # Group errors by severity
        error_count = sum(1 for e in errors if e.severity == "error")
        warning_count = sum(1 for e in errors if e.severity == "warning")
        info_count = sum(1 for e in errors if e.severity == "info")
        
        logger.info(f"📋 Configuration validation report: {error_count} errors, {warning_count} warnings, {info_count} recommendations")
        
        # Print errors by severity
        for severity in ["error", "warning", "info"]:
            severity_errors = [e for e in errors if e.severity == severity]
            if not severity_errors:
                continue
            
            severity_icon = {"error": "❌", "warning": "⚠️", "info": "💡"}[severity]
            logger.info(f"\n{severity_icon} {severity.upper()}S:")
            
            for error in severity_errors:
                logger.info(f"  • {error.field}: {error.message}")
        
        if error_count > 0:
            logger.error("Configuration validation failed due to errors. Please fix the issues above.")
        elif warning_count > 0:
            logger.warning("Configuration validation passed with warnings. Consider addressing the issues above.")
        else:
            logger.info("Configuration validation passed with recommendations.")
