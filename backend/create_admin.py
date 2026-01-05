"""Create an admin user in the database."""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal, init_db
from backend.models.db_models import Admin
from backend.auth import get_password_hash
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_admin(username: str, password: str, email: str = None):
    """Create an admin user."""
    init_db()  # Ensure database is initialized
    
    db = SessionLocal()
    try:
        # Check if admin already exists
        existing = db.query(Admin).filter(Admin.username == username).first()
        if existing:
            logger.warning(f"Admin '{username}' already exists!")
            return False
        
        # Ensure password is a string (get_password_hash will handle length validation)
        password_str = str(password) if password else ""
        if not password_str:
            logger.error("❌ Password cannot be empty!")
            return False
        
        # Create new admin (get_password_hash handles bcrypt 72-byte limit)
        admin = Admin(
            username=username,
            password_hash=get_password_hash(password_str),
            email=email,
            is_active=True
        )
        db.add(admin)
        db.commit()
        logger.info(f"✅ Admin '{username}' created successfully!")
        return True
    except Exception as e:
        logger.error(f"❌ Error creating admin: {e}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    import getpass
    
    print("Create Admin User")
    print("=" * 50)
    username = input("Username: ").strip()
    if not username:
        print("❌ Username cannot be empty!")
        sys.exit(1)
    
    password = getpass.getpass("Password: ")
    if not password:
        print("❌ Password cannot be empty!")
        sys.exit(1)
    
    # Check password length (bcrypt has 72 byte limit, NOT 72 characters)
    password_bytes = password.encode('utf-8')
    password_length_bytes = len(password_bytes)
    
    if password_length_bytes > 72:
        print(f"\n⚠️  WARNING: Your password is {password_length_bytes} bytes long.")
        print("   Bcrypt supports a maximum of 72 BYTES (not 72 characters).")
        print("   - For ASCII characters (a-z, A-Z, 0-9, basic symbols): 1 byte = 1 character")
        print("   - For non-ASCII characters (é, ñ, emojis, etc.): 1 character = 2-4 bytes")
        print(f"   - Your password will be truncated to 72 bytes.")
        print(f"   - Only the first {72} bytes will be used for authentication.")
        print("\n   RECOMMENDATION: Use a shorter password (max 72 ASCII characters)")
        print("   or ensure your password is <= 72 bytes when UTF-8 encoded.\n")
        
        response = input("   Continue with truncated password? (y/n): ").strip().lower()
        if response != 'y':
            print("❌ Cancelled. Please use a shorter password.")
            sys.exit(1)
    elif password_length_bytes == 72:
        print(f"✓ Password is exactly 72 bytes (maximum allowed).")
    else:
        print(f"✓ Password is {password_length_bytes} bytes (max: 72 bytes).")
    
    email = input("Email (optional): ").strip() or None
    
    if create_admin(username, password, email):
        print(f"\n✅ Admin user '{username}' created successfully!")
        print("You can now use these credentials to log in to the admin panel.")
    else:
        print("\n❌ Failed to create admin user.")
        sys.exit(1)

