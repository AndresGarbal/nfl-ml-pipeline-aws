import nfl_data as nfl
import json
import boto3
import pandas as pd
import sys
from datetime import datetime
import os
import math
import logging
import numpy as np
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def clean_dataframe(df):
    """Fully clean the DataFrame before serialization"""
    df = df.replace([np.nan, pd.NA, pd.NaT], None)

    for col in df.select_dtypes(include=['float64', 'float32']):
        df[col] = df[col].apply(lambda x: None if isinstance(x, float) and (math.isinf(x) or math.isnan(x)) else x)

    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].astype(str)

    return df

def get_optimal_chunk_size(records):
    """Compute the optimal chunk size based on the average record size"""
    sample_size = min(10, len(records))
    try:
        avg_size = sum(len(json.dumps(r, default=str)) for r in records[:sample_size]) / sample_size
        return max(1, min(50, int(200000 / avg_size)))
    except Exception:
        return 20

def send_to_lambda(data, stat_type, max_retries=3):
    """Send data to Lambda with robust error handling"""
    try:
        region = os.getenv('AWS_REGION', 'us-east-1')
        lambda_client = boto3.client('lambda', region_name=region)

        records = data.to_dict('records')
        chunk_size = get_optimal_chunk_size(records)
        total_chunks = len(records) // chunk_size + (1 if len(records) % chunk_size else 0)

        logger.info(f"Sending {len(records)} records in {total_chunks} chunks ({chunk_size} records per chunk)")

        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            payload = {
                'stat_type': stat_type,
                'data': chunk,
                'metadata': {
                    'total_chunks': total_chunks,
                    'current_chunk': i // chunk_size + 1,
                    'timestamp': datetime.now().isoformat()
                }
            }

            retry_count = 0
            while retry_count <= max_retries:
                try:
                    json_payload = json.dumps(payload, default=str)

                    if len(json_payload) > 250000:
                        raise ValueError(f"Payload too large: {len(json_payload)} bytes")

                    response = lambda_client.invoke(
                        FunctionName=os.getenv('NGS_DATA_LAMBDA', 'NGS_DATA_LAMBDA'),
                        InvocationType='RequestResponse',
                        Payload=json_payload
                    )

                    response_payload = response['Payload'].read().decode('utf-8')
                    if not response_payload:
                        raise ValueError("Empty response from Lambda")

                    result = json.loads(response_payload)

                    if response['StatusCode'] != 200:
                        error_msg = result.get('error', 'Unknown Lambda error')
                        logger.error(f"Lambda error: {error_msg}")
                        raise Exception(f"Lambda error: {error_msg}")

                    logger.info(f"Chunk {i//chunk_size + 1}/{total_chunks} processed. Inserted: {result.get('inserted_records', 0)}")
                    break

                except json.JSONDecodeError as je:
                    logger.error(f"Error decoding JSON (attempt {retry_count + 1}/{max_retries}): {str(je)}")
                    if retry_count == max_retries:
                        logger.error("Raw response:", response_payload[:500] if 'response_payload' in locals() else "Not available")
                        raise
                    retry_count += 1
                    time.sleep(2 ** retry_count)  # Exponential backoff

                except Exception as e:
                    logger.error(f"Error in chunk {i//chunk_size + 1}: {str(e)}")
                    if retry_count == max_retries:
                        logger.error("First problematic record:", chunk[0] if chunk else "No records")
                        with open(f'error_chunk_{stat_type}_{i}.json', 'w') as f:
                            json.dump({'error': str(e), 'data': chunk[0] if chunk else None}, f)
                        raise
                    retry_count += 1
                    time.sleep(1)

        return True

    except Exception as e:
        logger.error(f"Fatal error sending data to Lambda: {str(e)}", exc_info=True)
        return False

def process_and_send_data(years, stat_type):
    """Process data and send it to Lambda"""
    try:
        logger.info(f"\n{'='*50}")
        logger.info(f"Fetching {stat_type} data for years {years}")

        df = nfl.import_ngs_data(years=years, stat_type=stat_type)

        if df.empty:
            logger.warning(f"No data found for {stat_type} in {years}")
            return

        df.columns = df.columns.str.lower()
        df = clean_dataframe(df)

        logger.info("Data summary before sending:")
        logger.info(f"Total records: {len(df)}")
        logger.info(f"Null values per column:\n{df.isnull().sum()}")

        # First test with just 2 records
        test_success = send_to_lambda(df.head(2), stat_type)
        if not test_success:
            raise Exception("The 2-record test failed")

        logger.info("2-record test succeeded. Sending all data...")
        full_success = send_to_lambda(df, stat_type)

        if full_success:
            logger.info(f"{stat_type} data processed and sent successfully")
        else:
            logger.error(f"There were problems sending {stat_type} data")

    except Exception as e:
        logger.error(f"Error in process_and_send_data: {str(e)}", exc_info=True)

if __name__ == '__main__':
    # Configuration
    years = [2025]
    stat_types = ['receiving','passing','rushing']

    for stat_type in stat_types:
        process_and_send_data(years, stat_type)
