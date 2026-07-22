import os
import sys
import json
import http.client
from time import sleep
import boto3
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import Any, List, Dict, Optional
from schedule_model import Schedule, Body, GameStatus

# Exit codes
EXIT_SUCCESS = 0          # Processed data successfully
EXIT_ERROR = 1            # Real error
EXIT_DATA_NOT_READY = 2   # Data not available (retry tomorrow)
EXIT_ALREADY_PROCESSED = 3  # Week already processed

# Initial configuration
load_dotenv()
YEARS = [2025]
DATA_DIR = "data"
BOXSCORE_DIR = os.path.join(DATA_DIR, "boxscores")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BOXSCORE_DIR, exist_ok=True)

# Request headers
RAPIDAPI_HEADERS = {
    'x-rapidapi-key': os.getenv("RAPIDAPI_KEY"),
    'x-rapidapi-host': "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
}

# AWS configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LAMBDA_FUNCTION_NAME = os.getenv("RAPIDAPI_FUNCTION", "nfl-stats-processor")

# SSM client (Systems Manager Parameter Store)
ssm_client = boto3.client('ssm', region_name=AWS_REGION)

# Parameter names in Parameter Store
PARAM_LAST_WEEK = "/nfl-stats/last-processed-week"
PARAM_CURRENT_SEASON = "/nfl-stats/current-season"
PARAM_SEASON_START = "/nfl-stats/season-start-date"

def get_ssm_parameter(param_name: str, default_value: str = None) -> str:
    """Get a parameter from AWS Systems Manager Parameter Store"""
    try:
        response = ssm_client.get_parameter(Name=param_name)
        return response['Parameter']['Value']
    except ssm_client.exceptions.ParameterNotFound:
        print(f"⚠️ Parameter {param_name} not found. Using default value: {default_value}")
        if default_value is not None:
            # Create the parameter with the default value
            ssm_client.put_parameter(
                Name=param_name,
                Value=default_value,
                Type='String',
                Overwrite=False
            )
        return default_value
    except Exception as e:
        print(f"Error getting parameter {param_name}: {str(e)}")
        return default_value

def update_ssm_parameter(param_name: str, value: str) -> bool:
    """Update a parameter in AWS Systems Manager Parameter Store"""
    try:
        ssm_client.put_parameter(
            Name=param_name,
            Value=value,
            Type='String',
            Overwrite=True
        )
        print(f"✅ Parameter {param_name} updated to: {value}")
        return True
    except Exception as e:
        print(f"Error updating parameter {param_name}: {str(e)}")
        return False

def calculate_current_nfl_week(season_start_str: str) -> int:
    """
    Compute the current NFL week based on the season start date.
    NFL weeks run Thursday to Wednesday.
    """
    try:
        season_start = datetime.strptime(season_start_str, "%Y-%m-%d")
        today = datetime.now()

        # Days elapsed since the start
        days_elapsed = (today - season_start).days

        # NFL games run mostly Thursday-Monday, week closes Tuesday/Wednesday
        # Each week is 7 days
        current_week = (days_elapsed // 7) + 1

        # Validation: the NFL regular season has 18 weeks
        if current_week < 1:
            return 1
        elif current_week > 18:
            return 18

        return current_week
    except Exception as e:
        print(f"Error calculating NFL week: {str(e)}")
        return 1

def get_week_to_process() -> tuple[int, int, bool]:
    """
    Determine which week should be processed based on:
    1. The last processed week (from Parameter Store)
    2. The computed current week
    3. The current season

    Returns:
        tuple: (week_to_process, current_season, should_process)
    """
    # Get parameters from AWS
    last_processed_week = int(get_ssm_parameter(PARAM_LAST_WEEK, "0"))
    current_season = int(get_ssm_parameter(PARAM_CURRENT_SEASON, "2025"))
    season_start_date = get_ssm_parameter(PARAM_SEASON_START, "2025-09-04")

    # Compute current week
    current_week = calculate_current_nfl_week(season_start_date)

    print(f"\n📊 Current state:")
    print(f"   - Last processed week: {last_processed_week}")
    print(f"   - Current NFL week: {current_week}")
    print(f"   - Season: {current_season}")

    # Decide whether to process
    if current_week > last_processed_week:
        week_to_process = last_processed_week + 1
        print(f"   ✅ Will process week: {week_to_process}")
        return week_to_process, current_season, True
    else:
        print(f"   ⏭️ No new week to process (waiting for week {last_processed_week + 1})")
        return last_processed_week, current_season, False

def validate_all_games_final(schedule: Schedule) -> bool:
    """
    Check that ALL games in the week have status Final or Final/OT.
    Returns True if all are finished, False if any is not.
    """
    final_statuses = {GameStatus.FINAL, GameStatus.FINAL_OT}
    not_final = []

    for game in schedule.body:
        if game.game_status not in final_statuses:
            not_final.append(f"{game.away} @ {game.home} ({game.game_status.value})")

    if not_final:
        print(f"\n⚠️ {len(not_final)} game(s) are NOT finished:")
        for game_desc in not_final:
            print(f"   - {game_desc}")
        return False

    print(f"\n✅ All {len(schedule.body)} games are finished.")
    return True


def mark_week_as_processed(week: int) -> bool:
    """Mark a week as processed in Parameter Store"""
    return update_ssm_parameter(PARAM_LAST_WEEK, str(week))

def get_rapidapi_games(week: int, season_type: str = "reg", season: int = 2025) -> Any:
    """Get game data for a specific week."""
    conn = http.client.HTTPSConnection("tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com")
    try:
        endpoint = f"/getNFLGamesForWeek?week={week}&seasonType={season_type}&season={season}"
        conn.request("GET", endpoint, headers=RAPIDAPI_HEADERS)
        res = conn.getresponse()
        if res.status == 200:
            return json.loads(res.read().decode("utf-8"))
        else:
            print(f"Error in week {week}: {res.status} - {res.reason}")
            return None
    except Exception as e:
        print(f"API error (week {week}): {str(e)}")
        return None
    finally:
        conn.close()

def get_boxscore_data(game_id: str) -> Dict:
    """Get boxscore data for a specific game_id"""
    conn = http.client.HTTPSConnection("tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com")

    params = (
        f"gameID={game_id}&"
        "playByPlay=true&"
        "fantasyPoints=true&"
        "twoPointConversions=2&"
        "passYards=.04&"
        "passTD=4&"
        "passInterceptions=-2&"
        "pointsPerReception=.5&"
        "rushYards=.1&"
        "rushTD=6&"
        "fumbles=-2&"
        "receivingYards=.1&"
        "receivingTD=6"
    )

    try:
        conn.request("GET", f"/getNFLBoxScore?{params}", headers=RAPIDAPI_HEADERS)
        res = conn.getresponse()
        if res.status == 200:
            return json.loads(res.read().decode("utf-8"))
        else:
            print(f"Error in game_id {game_id}: {res.status} - {res.reason}")
            return None
    except Exception as e:
        print(f"API error (game_id {game_id}): {str(e)}")
        return None
    finally:
        conn.close()

def send_to_lambda(payload: Dict, lambda_function_name: str) -> bool:
    """Send data to the AWS Lambda function"""
    try:
        lambda_client = boto3.client('lambda', region_name=AWS_REGION)

        response = lambda_client.invoke(
            FunctionName=lambda_function_name,
            InvocationType='Event',  # Asynchronous
            Payload=json.dumps(payload)
        )

        if response['StatusCode'] in [200, 202]:
            print(f"Data sent successfully to Lambda {lambda_function_name}")
            return True
        else:
            print(f"Error sending to Lambda: {response}")
            return False
    except Exception as e:
        print(f"AWS Lambda error: {str(e)}")
        return False

def process_boxscore_data(boxscore_data: Dict, game_id: str, week: int, season: int) -> Optional[Dict]:
    """Process boxscore data and return a structured dict for Lambda"""
    if not boxscore_data or 'body' not in boxscore_data:
        return None

    try:
        body = boxscore_data['body']
        processed_data = {
            'game_info': {
                'game_id': str(game_id),
                'week': week,
                'season': season,
                'home_team': str(body.get('home', '')),
                'away_team': str(body.get('away', '')),
                'home_pts': int(body.get('homePts', 0)),
                'away_pts': int(body.get('awayPts', 0)),
                'game_status': str(body.get('gameStatus', '')),
                'game_date': int(body.get('gameDate', 0))
            },
            'player_stats': [],
            'team_stats': [],
            'scoring_plays': [],
            'dst_stats': []
        }

        # 1. Process Player Stats
        for player_id, stats in body.get('playerStats', {}).items():
            try:
                player_data = {
                    'player_id': str(player_id),
                    'player_name': str(stats.get('longName', '')),
                    'team': str(stats.get('team', '')),
                    'team_abv': str(stats.get('teamAbv', '')),
                    'team_id': int(stats.get('teamID', 0)),
                    'game_id': str(game_id),
                    'position': '',  # Can be extracted from the name if needed
                    'stats': {}
                }

                # Add stats by type
                for stat_type in ['Passing', 'Rushing', 'Receiving', 'Defense', 'Kicking', 'Punting']:
                    if stat_type in stats:
                        player_data['stats'][stat_type.lower()] = stats[stat_type]

                processed_data['player_stats'].append(player_data)
            except Exception as e:
                print(f"Error processing player {player_id}: {str(e)}")

        # 2. Process Team Stats
        team_stats = body.get('teamStats', {})
        for team_side in ['away', 'home']:
            if team_side in team_stats:
                try:
                    team_data = team_stats[team_side]
                    processed_data['team_stats'].append({
                        'team': str(team_data.get('team', '')),
                        'team_abv': str(team_data.get('teamAbv', '')),
                        'team_id': int(team_data.get('teamID', 0)),
                        'side': team_side,
                        'total_yards': int(team_data.get('totalYards', 0)),
                        'passing_yards': int(team_data.get('passingYards', 0)),
                        'rushing_yards': int(team_data.get('rushingYards', 0)),
                        'turnovers': int(team_data.get('turnovers', 0)),
                        'first_downs': int(team_data.get('firstDowns', 0)),
                        'sacks': team_data.get('sacksAndYardsLost', '0-0').split('-')[0],
                        'third_down_eff': str(team_data.get('thirdDownEfficiency', '')),
                        'redzone_eff': str(team_data.get('redZoneScoredAndAttempted', ''))
                    })
                except Exception as e:
                    print(f"Error processing team {team_side}: {str(e)}")

        # 3. Process Scoring Plays
        for play in body.get('scoringPlays', []):
            try:
                processed_data['scoring_plays'].append({
                    'period': str(play.get('scorePeriod', '')),
                    'time': str(play.get('scoreTime', '')),
                    'team': str(play.get('team', '')),
                    'team_id': int(play.get('teamID', 0)),
                    'type': str(play.get('scoreType', '')),
                    'details': str(play.get('scoreDetails', '')),
                    'points': str(play.get('score', '')),
                    'home_score': int(play.get('homeScore', 0)),
                    'away_score': int(play.get('awayScore', 0)),
                    'player_ids': [str(pid) for pid in play.get('playerIDs', [])]
                })
            except Exception as e:
                print(f"Error processing scoring play: {str(e)}")

        # 4. Process DST Stats
        dst = body.get('DST', {})
        for team_side in ['away', 'home']:
            if team_side in dst:
                try:
                    team_data = dst[team_side]
                    processed_data['dst_stats'].append({
                        'team': team_side,
                        'team_abv': str(team_data.get('teamAbv', '')),
                        'team_id': int(team_data.get('teamID', 0)),
                        'sacks': int(team_data.get('sacks', 0)),
                        'interceptions': int(team_data.get('defensiveInterceptions', 0)),
                        'points_allowed': int(team_data.get('ptsAllowed', 0)),
                        'fumbles_recovered': int(team_data.get('fumblesRecovered', 0)),
                        'defensive_tds': int(team_data.get('defTD', 0))
                    })
                except Exception as e:
                    print(f"Error processing DST stats {team_side}: {str(e)}")

        return processed_data

    except Exception as e:
        print(f"Severe error processing boxscore {game_id}: {str(e)}")
        return None

def fetch_boxscores_for_season(game_info_list: List[Dict]) -> bool:
    """Process boxscores and send data to Lambda"""
    all_success = True

    for game_info in game_info_list:
        game_id = game_info['game_id']
        print(f"Processing boxscore for {game_id} (Week {game_info['week']})...")

        boxscore_data = get_boxscore_data(game_id)
        if boxscore_data:
            processed_data = process_boxscore_data(
                boxscore_data,
                game_id,
                game_info['week'],
                game_info['season']
            )

            if processed_data:
                # Send data to Lambda
                success = send_to_lambda({
                    'action': 'process_boxscore',
                    'data': processed_data
                }, LAMBDA_FUNCTION_NAME)

                if not success:
                    print(f"Error sending game {game_id} data to Lambda")
                    all_success = False
        else:
            all_success = False

        sleep(1)  # Rate limiting

    return all_success

def fetch_and_save_week(week: int, season: int, season_type: str = "reg") -> tuple[Schedule, List[Dict], List[Dict], bool]:
    """
    Collect data for a specific week.
    Returns (schedule, game_info_list, all_games, success).
    Does NOT send data to Lambda — that happens after validation.
    """
    all_games = []
    game_info = []

    print(f"\n🏈 Fetching data for week {week} ({season})...")
    api_response = get_rapidapi_games(week, season_type, season)

    if not api_response:
        print(f"❌ Week {week} failed.")
        return None, game_info, all_games, False

    schedule = Schedule.from_dict(api_response)
    for game in schedule.body:
        game_info.append({
            'game_id': game.game_id,
            'week': week,
            'season': season
        })
        all_games.append({
            "season": season,
            "week": week,
            "game_id": game.game_id,
            "home_team": game.home,
            "away_team": game.away,
            "game_date": datetime.fromtimestamp(game.game_date).strftime("%Y-%m-%d"),
            "game_time": game.game_time,
            "neutral_site": game.neutral_site.value,
            "status": game.game_status.value,
            "espn_link": game.espn_link,
        })

    print(f"✅ Week {week} fetched: {len(all_games)} games")
    return schedule, game_info, all_games, True

def send_schedule_to_lambda(all_games: List[Dict]) -> bool:
    """Send schedule information to Lambda"""
    if not all_games:
        return False

    success = send_to_lambda({
        'action': 'process_schedule',
        'data': {
            'games': all_games
        }
    }, LAMBDA_FUNCTION_NAME)

    if success:
        print(f"📊 Schedule data sent to Lambda (Total: {len(all_games)} games).")
    else:
        print("❌ Error sending schedule data to Lambda")

    return success


def process_weekly_data():
    """
    Main function that determines and processes the corresponding week.

    Exit codes:
        0: Processed data successfully
        1: Real error
        2: Data not available (not all games are Final)
        3: Nothing to process (week already processed)
    """
    print("=" * 60)
    print("🏈 NFL STATS PROCESSOR - AUTOMATIC WEEK DETECTION")
    print("=" * 60)

    # Determine which week to process
    week_to_process, current_season, should_process = get_week_to_process()

    if not should_process:
        print("\n⏸️ No new weeks to process. Exiting...")
        sys.exit(EXIT_ALREADY_PROCESSED)

    # 1. Get schedule from the API
    schedule, game_info_list, all_games, fetch_success = fetch_and_save_week(week_to_process, current_season)

    if not fetch_success:
        print(f"\n❌ Error fetching data for week {week_to_process}.")
        sys.exit(EXIT_ERROR)

    # 2. Validate that all games are finished
    if not validate_all_games_final(schedule):
        print(f"\n⏳ Week {week_to_process}: data not ready. Retrying tomorrow.")
        sys.exit(EXIT_DATA_NOT_READY)

    # 3. Process boxscores
    print(f"\n📦 Fetching boxscores for week {week_to_process}...")
    boxscore_success = fetch_boxscores_for_season(game_info_list)

    if not boxscore_success:
        print(f"\n❌ Error processing boxscores for week {week_to_process}.")
        sys.exit(EXIT_ERROR)

    # 4. Only if boxscores succeeded: send schedule + mark as processed
    if not send_schedule_to_lambda(all_games):
        print(f"\n❌ Error sending schedule to Lambda.")
        sys.exit(EXIT_ERROR)

    if mark_week_as_processed(week_to_process):
        print(f"\n✅ Week {week_to_process} processed successfully and marked as complete.")
    else:
        print(f"\n⚠️ Week {week_to_process} processed but could not be marked in Parameter Store.")
        sys.exit(EXIT_ERROR)

    sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    if os.getenv("RAPIDAPI_KEY"):
        process_weekly_data()
    else:
        print("⚠️ RAPIDAPI_KEY not found in .env")
        sys.exit(EXIT_ERROR)
