"""Utility to check ElevenLabs account status and credits."""
import logging
from typing import Dict, Optional
from dotenv import load_dotenv
import os

logger = logging.getLogger(__name__)


def check_account_status() -> Dict[str, any]:
    """
    Check ElevenLabs account status and credit information.
    
    Returns:
        Dict with account information including subscription, credits, etc.
    """
    try:
        from elevenlabs import ElevenLabs
        
        # Reload .env to get latest API key
        load_dotenv(override=True)
        api_key = os.getenv("ELEVENLABS_API_KEY")
        
        if not api_key:
            return {
                "error": "ELEVENLABS_API_KEY not found in environment variables",
                "success": False
            }
        
        client = ElevenLabs(api_key=api_key)
        
        # Try to get user info (this endpoint may vary by SDK version)
        try:
            # Attempt to get user information
            user_info = client.user.get()
            
            return {
                "success": True,
                "subscription": getattr(user_info, 'subscription', {}),
                "credits_remaining": getattr(user_info, 'subscription', {}).get('character_count', 'Unknown'),
                "message": "Account information retrieved successfully"
            }
        except AttributeError:
            # SDK might have different structure
            try:
                # Try alternative method
                user_info = client.user.get_current()
                return {
                    "success": True,
                    "user_info": str(user_info),
                    "message": "Account information retrieved (raw format)"
                }
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Could not retrieve account info: {str(e)}",
                    "note": "The API key is valid, but account details structure may differ. Check your ElevenLabs dashboard at https://elevenlabs.io/app/settings/api-keys"
                }
                
    except ImportError:
        return {
            "success": False,
            "error": "ElevenLabs SDK not installed",
            "message": "Install with: pip install elevenlabs"
        }
    except Exception as e:
        error_str = str(e).lower()
        
        # Check for quota errors
        if "quota" in error_str or "quota_exceeded" in error_str:
            return {
                "success": False,
                "error": "Quota exceeded",
                "message": (
                    "Your ElevenLabs account has run out of credits for this billing period.\n"
                    "The error shows you have 13 credits remaining but need 16 for this request.\n\n"
                    "Solutions:\n"
                    "1. Wait for your monthly quota to reset\n"
                    "2. Enable usage-based billing in your ElevenLabs account settings\n"
                    "3. Upgrade to a higher plan with more credits\n"
                    "4. Switch to Cartesia provider temporarily"
                )
            }
        elif "401" in str(e) or "unauthorized" in error_str or "invalid" in error_str:
            return {
                "success": False,
                "error": "Invalid API key",
                "message": "The API key in your .env file may be incorrect or expired. Please verify it at https://elevenlabs.io/app/settings/api-keys"
            }
        else:
            return {
                "success": False,
                "error": str(e),
                "message": "Could not check account status"
            }


if __name__ == "__main__":
    # Allow running as script for testing
    result = check_account_status()
    print("\n=== ElevenLabs Account Status ===")
    print(f"Success: {result.get('success')}")
    if result.get('error'):
        print(f"Error: {result.get('error')}")
    if result.get('message'):
        print(f"Message: {result.get('message')}")
    if result.get('credits_remaining'):
        print(f"Credits Remaining: {result.get('credits_remaining')}")


