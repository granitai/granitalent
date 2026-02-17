"""Database migration script - adds missing columns to existing tables."""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import engine
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_database():
    """Add missing columns to existing database tables."""
    try:
        with engine.connect() as conn:
            # Check if required_languages column exists in job_offers table
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='required_languages'
            """))
            has_required_languages = result.fetchone()[0] > 0
            
            # Check if interview_start_language column exists
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='interview_start_language'
            """))
            has_interview_start_language = result.fetchone()[0] > 0
            
            # Add required_languages column if it doesn't exist
            if not has_required_languages:
                logger.info("Adding 'required_languages' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN required_languages TEXT DEFAULT ''
                """))
                conn.commit()
                logger.info("✅ Added 'required_languages' column")
            else:
                logger.info("Column 'required_languages' already exists")
            
            # Add interview_start_language column if it doesn't exist
            if not has_interview_start_language:
                logger.info("Adding 'interview_start_language' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN interview_start_language TEXT DEFAULT ''
                """))
                conn.commit()
                logger.info("✅ Added 'interview_start_language' column")
            else:
                logger.info("Column 'interview_start_language' already exists")
            
            # Check if interview_duration_minutes column exists
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='interview_duration_minutes'
            """))
            has_interview_duration = result.fetchone()[0] > 0
            
            # Add interview_duration_minutes column if it doesn't exist
            if not has_interview_duration:
                logger.info("Adding 'interview_duration_minutes' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN interview_duration_minutes INTEGER DEFAULT 20
                """))
                conn.commit()
                logger.info("✅ Added 'interview_duration_minutes' column (default: 20 minutes)")
            else:
                logger.info("Column 'interview_duration_minutes' already exists")
            
            # Check if custom_questions column exists
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='custom_questions'
            """))
            has_custom_questions = result.fetchone()[0] > 0
            
            # Add custom_questions column if it doesn't exist
            if not has_custom_questions:
                logger.info("Adding 'custom_questions' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN custom_questions TEXT DEFAULT ''
                """))
                conn.commit()
                logger.info("✅ Added 'custom_questions' column")
            else:
                logger.info("Column 'custom_questions' already exists")
            
            # Check if evaluation_weights column exists
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='evaluation_weights'
            """))
            has_evaluation_weights = result.fetchone()[0] > 0
            
            # Add evaluation_weights column if it doesn't exist
            if not has_evaluation_weights:
                logger.info("Adding 'evaluation_weights' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN evaluation_weights TEXT DEFAULT ''
                """))
                conn.commit()
                logger.info("✅ Added 'evaluation_weights' column")
            else:
                logger.info("Column 'evaluation_weights' already exists")
            
            # Check if interview_mode column exists
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM pragma_table_info('job_offers') 
                WHERE name='interview_mode'
            """))
            has_interview_mode = result.fetchone()[0] > 0
            
            # Add interview_mode column if it doesn't exist
            if not has_interview_mode:
                logger.info("Adding 'interview_mode' column to job_offers table...")
                conn.execute(text("""
                    ALTER TABLE job_offers 
                    ADD COLUMN interview_mode TEXT DEFAULT 'realtime'
                """))
                conn.commit()
                logger.info("✅ Added 'interview_mode' column (default: 'realtime')")
            else:
                logger.info("Column 'interview_mode' already exists")
            
            # Check and add missing columns in applications table
            logger.info("Checking applications table for missing columns...")
            
            # Get all existing columns in applications table
            result = conn.execute(text("""
                SELECT name FROM pragma_table_info('applications')
            """))
            existing_columns = {row[0] for row in result.fetchall()}
            
            # Define expected columns for applications table
            expected_columns = {
                'cover_letter_filename': ('TEXT', None),
                'cv_filename': ('TEXT', None),
                'is_archived': ('INTEGER', '0'),
                'archived_at': ('DATETIME', None),
            }
            
            # Add missing columns
            for column_name, (column_type, default_value) in expected_columns.items():
                if column_name not in existing_columns:
                    logger.info(f"Adding '{column_name}' column to applications table...")
                    if default_value is not None:
                        sql = f"ALTER TABLE applications ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                    else:
                        sql = f"ALTER TABLE applications ADD COLUMN {column_name} {column_type}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Added '{column_name}' column")
                else:
                    logger.info(f"Column '{column_name}' already exists")
            
            # Check and add missing columns in interviews table
            logger.info("Checking interviews table for missing columns...")
            
            # Get all existing columns in interviews table
            result = conn.execute(text("""
                SELECT name FROM pragma_table_info('interviews')
            """))
            existing_interview_columns = {row[0] for row in result.fetchall()}
            
            # Define expected columns for interviews table
            expected_interview_columns = {
                'evaluation_scores': ('TEXT', None),
                'recording_audio': ('TEXT', None),
                'provider_preferences': ('TEXT', None),
                'audio_segments': ('TEXT', None),
                'recording_video': ('TEXT', None),
                'is_archived': ('INTEGER', '0'),
                'archived_at': ('DATETIME', None),
            }
            
            # Add missing columns
            for column_name, (column_type, default_value) in expected_interview_columns.items():
                if column_name not in existing_interview_columns:
                    logger.info(f"Adding '{column_name}' column to interviews table...")
                    if default_value is not None:
                        sql = f"ALTER TABLE interviews ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                    else:
                        sql = f"ALTER TABLE interviews ADD COLUMN {column_name} {column_type}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Added '{column_name}' column")
                else:
                    logger.info(f"Column '{column_name}' already exists")
            
            logger.info("✅ Database migration completed successfully!")
            
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Starting database migration...")
    migrate_database()

