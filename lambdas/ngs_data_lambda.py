"""
NGS_DATA_LAMBDA — Inserts the Next Gen Stats (passing / receiving / rushing) sent in
chunks from `get_ngs.py` into the corresponding RDS PostgreSQL tables. Credentials via
environment variables.
"""
import json
import psycopg2
from psycopg2 import sql
import os
import logging
import sys
from datetime import datetime

# Logging to CloudWatch
logger = logging.getLogger()
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s\n'
    'File: %(pathname)s\nLine: %(lineno)d\n'
)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
logger.addHandler(handler)

def log_event_details(event):
    """Log full details of the received event"""
    try:
        logger.debug("=== EVENT START ===")
        logger.debug(f"Event type: {type(event)}")
        logger.debug(f"Stat type received: {event.get('stat_type')}")
        logger.debug(f"Number of records: {len(event.get('data', []))}")

        if 'metadata' in event:
            logger.debug(f"Metadata: {event['metadata']}")

        if event.get('data'):
            logger.debug("Sample of the first record:")
            logger.debug(json.dumps(event['data'][0], indent=2))
    except Exception as e:
        logger.error(f"Error logging event details: {str(e)}")

def get_db_connection():
    """Open a database connection with detailed verification"""
    try:
        logger.info("Attempting database connection...")
        logger.debug(f"DB_HOST: {os.environ.get('DB_HOST')}")
        logger.debug(f"DB_NAME: {os.environ.get('DB_NAME')}")
        logger.debug(f"DB_USER: {os.environ.get('DB_USER')}")
        logger.debug(f"DB_PORT: {os.environ.get('DB_PORT')}")

        conn = psycopg2.connect(
            host=os.environ['DB_HOST'],
            database=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS'],
            port=os.environ['DB_PORT'],
            connect_timeout=5
        )
        conn.autocommit = False

        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            db_version = cur.fetchone()
            logger.info(f"Connected to: {db_version[0]}")

            cur.execute("SELECT current_database()")
            db_name = cur.fetchone()
            logger.info(f"Current database: {db_name[0]}")

        return conn
    except Exception as e:
        logger.error("DB connection error", exc_info=True)
        raise

def insert_data(conn, table_name, data):
    """Insert function with detailed logging"""
    if not data:
        logger.warning("No data to insert")
        return {"inserted": 0, "errors": 0, "details": "No data provided"}

    columns = list(data[0].keys())
    inserted_count = 0
    error_count = 0
    error_details = []

    logger.info(f"Preparing to insert {len(data)} records into {table_name}")
    logger.debug(f"Columns to insert: {columns}")

    insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table_name),
        sql.SQL(', ').join(map(sql.Identifier, columns)),
        sql.SQL(', ').join([sql.Placeholder()] * len(columns))
    )

    try:
        with conn.cursor() as cursor:
            for i, record in enumerate(data):
                try:
                    values = [record.get(col) for col in columns]
                    logger.debug(f"Record {i+1}/{len(data)}: {values}")

                    cursor.execute(insert_sql, values)
                    inserted_count += 1

                    if (i+1) % 100 == 0:
                        logger.info(f"Progress: {i+1}/{len(data)} records processed")

                except psycopg2.IntegrityError as ie:
                    error_count += 1
                    error_msg = f"IntegrityError: {str(ie)}"
                    error_details.append({
                        "error": error_msg,
                        "record": record,
                        "type": "IntegrityError"
                    })
                    logger.warning(f"Integrity error on record {i+1}: {error_msg}")
                    conn.rollback()

                except psycopg2.Error as pe:
                    error_count += 1
                    error_msg = f"PostgreSQL Error [{pe.pgcode}]: {pe.pgerror}"
                    error_details.append({
                        "error": error_msg,
                        "record": record,
                        "type": "PostgreSQLError"
                    })
                    logger.error(f"PostgreSQL error on record {i+1}: {error_msg}")
                    conn.rollback()

                except Exception as e:
                    error_count += 1
                    error_msg = f"Unexpected Error: {str(e)}"
                    error_details.append({
                        "error": error_msg,
                        "record": record,
                        "type": "UnexpectedError"
                    })
                    logger.error(f"Unexpected error on record {i+1}: {error_msg}", exc_info=True)
                    conn.rollback()

            conn.commit()
            logger.info(f"Insertion complete. Inserted: {inserted_count}, Errors: {error_count}")

            return {
                "inserted": inserted_count,
                "errors": error_count,
                "details": error_details[:3] if error_count > 0 else "All successful"
            }

    except Exception as e:
        conn.rollback()
        logger.error("General error during insertion", exc_info=True)
        return {"inserted": 0, "errors": len(data), "details": str(e)}

def lambda_handler(event, context):
    """Main handler with full traceability"""
    logger.info("=== LAMBDA EXECUTION START ===")
    logger.debug(f"Lambda context: {vars(context)}")

    try:
        log_event_details(event)

        if not event.get('data'):
            raise ValueError("Event contains no data ('data' missing)")
        if not event.get('stat_type'):
            raise ValueError("Event contains no stat_type")

        table_map = {
            'passing': 'nfl_ngs_passing_data',
            'receiving': 'nfl_receiving_data',
            'rushing': 'nfl_ngs_rushing_data'
        }

        stat_type = event['stat_type']
        if stat_type not in table_map:
            raise ValueError(f"Invalid stat type: {stat_type}")

        table_name = table_map[stat_type]
        logger.info(f"Processing stats of type: {stat_type} into table: {table_name}")

        conn = get_db_connection()

        # Get the real columns of the target table
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_name} LIMIT 0")
            db_columns = [desc[0] for desc in cur.description]
            logger.debug(f"Columns found in table: {db_columns}")

        # Filter and transform data
        filtered_data = []
        for i, record in enumerate(event['data']):
            try:
                filtered_record = {k.lower(): v for k, v in record.items() if k.lower() in db_columns}

                for key, value in filtered_record.items():
                    if isinstance(value, float) and str(value) == 'nan':
                        filtered_record[key] = None
                    elif value == '':
                        filtered_record[key] = None

                filtered_data.append(filtered_record)

                if i == 0:
                    logger.debug("First record processed:")
                    logger.debug(json.dumps(filtered_record, indent=2))
            except Exception as e:
                logger.error(f"Error processing record {i}: {str(e)}")
                continue

        logger.info(f"Total valid records to insert: {len(filtered_data)}")

        result = insert_data(conn, table_name, filtered_data)

        response = {
            'statusCode': 200,
            'body': {
                'stat_type': stat_type,
                'total_records': len(event['data']),
                'inserted_records': result['inserted'],
                'error_records': result['errors'],
                'sample_errors': result['details'] if isinstance(result['details'], list) else [],
                'metadata': event.get('metadata', {})
            }
        }

        logger.info("=== RESPONSE ===")
        logger.debug(json.dumps(response, indent=2))

        return response

    except Exception as e:
        logger.error("Error in lambda_handler", exc_info=True)
        error_response = {
            'statusCode': 500,
            'body': {
                'error': str(e),
                'error_type': type(e).__name__,
                'stat_type': event.get('stat_type'),
                'timestamp': datetime.now().isoformat(),
                'event_received': {
                    'stat_type': event.get('stat_type'),
                    'data_length': len(event.get('data', [])),
                    'metadata': event.get('metadata', {})
                }
            }
        }
        logger.error("=== ERROR RESPONSE ===")
        logger.error(json.dumps(error_response, indent=2))

        return error_response
    finally:
        if 'conn' in locals():
            conn.close()
            logger.info("DB connection closed")
        logger.info("=== LAMBDA EXECUTION END ===")
