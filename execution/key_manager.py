"""
Key Manager - AES-256 encryption for sub-wallet private keys at rest.

This module provides secure encryption/decryption for Solana wallet private keys
stored in the database. It uses AES-256-GCM for authenticated encryption.

Usage:
    key_manager = AESKeyManager(os.getenv("KEY_ENCRYPTION_SECRET"))
    
    # Encrypt a private key before storing
    encrypted = key_manager.encrypt_key(private_key_bytes)
    
    # Decrypt when needed for signing
    decrypted = key_manager.decrypt_key(encrypted)
"""

import os
import base64
import secrets
import hashlib
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# AES-256-GCM parameters
KEY_SIZE = 32  # 256 bits
NONCE_SIZE = 12  # 96 bits (recommended for GCM)
TAG_SIZE = 16  # 128 bits authentication tag

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False
    logger.warning("cryptography library not installed. AES encryption unavailable.")


class KeyEncryptionError(Exception):
    """Raised when key encryption/decryption fails."""
    pass


class AESKeyManager:
    """
    Manages encryption/decryption of private keys using AES-256-GCM.
    
    Security Features:
    - AES-256-GCM provides authenticated encryption (confidentiality + integrity)
    - Unique random nonce for each encryption operation
    - Master key derived from secret using PBKDF2-like approach (SHA-256)
    - Constant-time comparison for authentication tags (handled by AESGCM)
    
    Storage Format:
    - Encrypted data is stored as base64: nonce (12 bytes) || ciphertext || tag (16 bytes)
    
    WARNING:
    - Keep KEY_ENCRYPTION_SECRET secure and backed up
    - If the secret is lost, all encrypted keys are unrecoverable
    - Rotate keys periodically by re-encrypting with new secret
    """
    
    def __init__(self, encryption_secret: str):
        """
        Initialize the key manager with a master encryption secret.
        
        Args:
            encryption_secret: Master secret for key derivation (from env var)
            
        Raises:
            ValueError: If secret is missing or too weak
            ImportError: If cryptography library not installed
        """
        if not HAS_CRYPTOGRAPHY:
            raise ImportError(
                "cryptography library required for key encryption. "
                "Install with: pip install cryptography"
            )
        
        if not encryption_secret:
            raise ValueError(
                "KEY_ENCRYPTION_SECRET is required. "
                "Set it in your .env file or environment."
            )
        
        if len(encryption_secret) < 16:
            raise ValueError(
                "KEY_ENCRYPTION_SECRET must be at least 16 characters. "
                "Use a strong, random secret."
            )
        
        # Derive a 256-bit key from the secret using SHA-256
        # In production, consider using PBKDF2 or Argon2 with salt
        self._master_key = self._derive_key(encryption_secret)
        self._cipher = AESGCM(self._master_key)
        
        logger.info("AES Key Manager initialized successfully")
    
    def _derive_key(self, secret: str) -> bytes:
        """
        Derive a 256-bit key from the master secret.
        
        Uses SHA-256 for simplicity. For enhanced security, 
        consider PBKDF2 with high iteration count or Argon2.
        """
        # Simple derivation - hash the secret
        # Adding a static domain separator for this application
        domain = b"solana-intel-engine:key-encryption:v1"
        combined = domain + secret.encode('utf-8')
        return hashlib.sha256(combined).digest()
    
    def encrypt_key(self, private_key: bytes) -> str:
        """
        Encrypt a private key for storage.
        
        Args:
            private_key: Raw private key bytes (typically 64 bytes for Ed25519)
            
        Returns:
            Base64-encoded encrypted data (nonce || ciphertext || tag)
            
        Raises:
            KeyEncryptionError: If encryption fails
        """
        if not private_key:
            raise KeyEncryptionError("Cannot encrypt empty key")
        
        try:
            # Generate a random nonce for this encryption
            nonce = secrets.token_bytes(NONCE_SIZE)
            
            # Encrypt with AES-GCM (includes authentication tag)
            ciphertext = self._cipher.encrypt(nonce, private_key, None)
            
            # Combine: nonce || ciphertext (which includes tag at end)
            encrypted_data = nonce + ciphertext
            
            # Encode as base64 for safe storage
            encoded = base64.b64encode(encrypted_data).decode('utf-8')
            
            logger.debug(f"Encrypted key: {len(private_key)} bytes -> {len(encoded)} chars")
            
            return encoded
            
        except Exception as e:
            logger.error(f"Key encryption failed: {e}")
            raise KeyEncryptionError(f"Failed to encrypt key: {e}")
    
    def decrypt_key(self, encrypted: str) -> bytes:
        """
        Decrypt a stored private key.
        
        Args:
            encrypted: Base64-encoded encrypted data from encrypt_key()
            
        Returns:
            Raw private key bytes
            
        Raises:
            KeyEncryptionError: If decryption fails (wrong key, tampered data, etc.)
        """
        if not encrypted:
            raise KeyEncryptionError("Cannot decrypt empty data")
        
        try:
            # Decode from base64
            encrypted_data = base64.b64decode(encrypted)
            
            # Extract nonce (first 12 bytes)
            if len(encrypted_data) < NONCE_SIZE + TAG_SIZE:
                raise KeyEncryptionError("Encrypted data too short")
            
            nonce = encrypted_data[:NONCE_SIZE]
            ciphertext = encrypted_data[NONCE_SIZE:]
            
            # Decrypt with AES-GCM (verifies authentication tag)
            private_key = self._cipher.decrypt(nonce, ciphertext, None)
            
            logger.debug(f"Decrypted key: {len(encrypted)} chars -> {len(private_key)} bytes")
            
            return private_key
            
        except Exception as e:
            logger.error(f"Key decryption failed: {e}")
            raise KeyEncryptionError(
                f"Failed to decrypt key. Possible causes: wrong secret, corrupted data. Error: {e}"
            )
    
    def generate_keypair(self) -> Tuple[str, bytes]:
        """
        Generate a new Solana keypair.
        
        Returns:
            Tuple of (public_key_base58, private_key_bytes)
            
        Note:
            This is a placeholder. In production, use solders or solana-py.
        """
        # Generate 64 random bytes for Ed25519 keypair seed
        # In real implementation: use solders.keypair.Keypair()
        
        try:
            # Try using solders if available
            from solders.keypair import Keypair
            
            kp = Keypair()
            address = str(kp.pubkey())
            private_key = bytes(kp)
            
            logger.info(f"Generated new keypair: {address[:16]}...")
            return address, private_key
            
        except ImportError:
            # Fallback: generate random bytes (NOT VALID for actual Solana use)
            logger.warning("solders not installed. Generating mock keypair.")
            
            # 64 bytes = 32-byte seed + 32-byte public key
            mock_private = secrets.token_bytes(64)
            # Generate a fake but valid-looking base58 address
            mock_address = base64.b58encode(secrets.token_bytes(32)).decode()[:44]
            
            return mock_address, mock_private


def create_key_manager() -> AESKeyManager:
    """
    Factory function to create a KeyManager from environment.
    
    Returns:
        Configured AESKeyManager instance
        
    Raises:
        ValueError: If KEY_ENCRYPTION_SECRET not set
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    secret = os.getenv("KEY_ENCRYPTION_SECRET")
    if not secret or secret == "your-encryption-secret-here":
        raise ValueError(
            "Set KEY_ENCRYPTION_SECRET in your .env file. "
            "Generate a strong random secret (32+ characters recommended)."
        )
    
    return AESKeyManager(secret)


# Utility for generating a new encryption secret
def generate_encryption_secret() -> str:
    """Generate a cryptographically secure random secret for KEY_ENCRYPTION_SECRET."""
    return secrets.token_urlsafe(32)
