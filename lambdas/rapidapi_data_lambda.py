"""
RAPIDAPI_DATA_LAMBDA — Receives the schedule and boxscore data sent from
`rapidapi.py` and upserts it idempotently into RDS PostgreSQL:
nfl_games, nfl_player_stats, nfl_team_stats, nfl_scoring_plays, nfl_season_dst_stats.
Credentials via environment variables.
"""
import json
import os
import psycopg2
from psycopg2.extras import execute_batch
from datetime import datetime

def get_db_connection():
    """Open a connection to the RDS PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            database=os.getenv('DB_NAME'),
            connect_timeout=5
        )
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to PostgreSQL: {e}")
        raise

def safe_int(value, default=None):
    """Safely convert to int"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def lambda_handler(event, context):
    print(f"Event received: {json.dumps(event)}")

    try:
        action = event.get('action')
        data = event.get('data')

        if not action or not data:
            return {'statusCode': 400, 'body': 'Missing action or data in the event'}

        if action == 'process_schedule':
            return process_schedule_data(data)
        elif action == 'process_boxscore':
            return process_boxscore_data(data)
        else:
            return {'statusCode': 400, 'body': f'Unsupported action: {action}'}

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {'statusCode': 500, 'body': f'Internal error: {str(e)}'}

def process_schedule_data(data):
    games = data.get('games', [])
    if not games:
        return {'statusCode': 400, 'body': 'No game data to process'}

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            game_data = []
            for game in games:
                game_date = datetime.strptime(game['game_date'], "%Y-%m-%d").date() if isinstance(game['game_date'], str) else game['game_date']
                game_data.append((
                    str(safe_int(game['season'])),  # varchar in nfl_games
                    str(safe_int(game['week'])),    # varchar in nfl_games
                    game['game_id'],
                    game['home_team'],
                    game['away_team'],
                    game_date,
                    game['game_time'],
                    str(game['neutral_site']).lower() == 'true',
                    game['status'],
                    game['espn_link']
                ))

            try:
                execute_batch(
                    cursor,
                    """
                    INSERT INTO public.nfl_games (
                        season, week, game_id, home_team, away_team, game_date,
                        game_time, neutral_site, status, espn_link
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id) DO UPDATE SET
                        home_team = EXCLUDED.home_team,
                        away_team = EXCLUDED.away_team,
                        game_date = EXCLUDED.game_date,
                        game_time = EXCLUDED.game_time,
                        neutral_site = EXCLUDED.neutral_site,
                        status = EXCLUDED.status,
                        espn_link = EXCLUDED.espn_link
                    """,
                    game_data
                )
                conn.commit()
                print(f"nfl_games: {len(games)} rows inserted/updated")
            except Exception as e:
                conn.rollback()
                print(f"Error in nfl_games: {e}")
                return {'statusCode': 500, 'body': str(e)}

        return {'statusCode': 200, 'body': f'Processed {len(games)} games'}

    except Exception as e:
        print(f"Error processing schedule: {str(e)}")
        if conn:
            conn.rollback()
        return {'statusCode': 500, 'body': f'Error processing schedule: {str(e)}'}
    finally:
        if conn:
            conn.close()

def process_boxscore_data(data):
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            game_info = data.get('game_info', {})
            if not game_info:
                return {'statusCode': 400, 'body': 'Missing game data'}

            season = safe_int(game_info['season'])
            week = safe_int(game_info['week'])
            game_id = game_info['game_id']

            # ---------------- nfl_player_stats ----------------
            try:
                player_stats = data.get('player_stats', [])
                if player_stats:
                    player_data = []
                    for player in player_stats:
                        stats = player.get('stats', {})
                        player_data.append((
                            season,
                            week,
                            game_id,
                            player['player_id'],
                            player['player_name'],
                            player['team'],
                            player.get('position', ''),
                            stats.get('defense', {}).get('totalTackles'),
                            stats.get('defense', {}).get('defTD'),
                            stats.get('defense', {}).get('forcedFumbles'),
                            stats.get('defense', {}).get('soloTackles'),
                            float(stats.get('defense', {}).get('tfl', 0)) if stats.get('defense', {}).get('tfl') else None,
                            stats.get('defense', {}).get('qbHits'),
                            stats.get('defense', {}).get('defensiveInterceptions'),
                            float(stats.get('defense', {}).get('sacks', 0)) if stats.get('defense', {}).get('sacks') else None,
                            stats.get('defense', {}).get('passDeflections'),
                            stats.get('kicking', {}).get('kickReturns'),
                            stats.get('kicking', {}).get('kickReturnTD'),
                            stats.get('kicking', {}).get('kickReturnYds'),
                            float(stats.get('kicking', {}).get('kickReturnAvg', 0)) if stats.get('kicking', {}).get('kickReturnAvg') else None,
                            stats.get('kicking', {}).get('kickReturnLong'),
                            stats.get('receiving', {}).get('receptions'),
                            stats.get('receiving', {}).get('recTD'),
                            stats.get('receiving', {}).get('longRec'),
                            stats.get('receiving', {}).get('targets'),
                            stats.get('receiving', {}).get('recYds'),
                            float(stats.get('receiving', {}).get('recAvg', 0)) if stats.get('receiving', {}).get('recAvg') else None,
                            float(stats.get('rushing', {}).get('rushAvg', 0)) if stats.get('rushing', {}).get('rushAvg') else None,
                            stats.get('rushing', {}).get('rushYds'),
                            stats.get('rushing', {}).get('carries'),
                            stats.get('rushing', {}).get('longRush'),
                            stats.get('rushing', {}).get('rushTD'),
                            stats.get('kicking', {}).get('fgLong'),
                            stats.get('kicking', {}).get('fgMade'),
                            stats.get('kicking', {}).get('fgAttempts'),
                            stats.get('kicking', {}).get('xpMade'),
                            float(stats.get('kicking', {}).get('fgPct', 0)) if stats.get('kicking', {}).get('fgPct') else None,
                            stats.get('kicking', {}).get('kickingPts'),
                            stats.get('kicking', {}).get('xpAttempts'),
                            stats.get('kicking', {}).get('fgMissed'),
                            stats.get('kicking', {}).get('xpMissed'),
                            float(stats.get('passing', {}).get('qbr', 0)) if stats.get('passing', {}).get('qbr') else None,
                            float(stats.get('passing', {}).get('rtg', 0)) if stats.get('passing', {}).get('rtg') else None,
                            stats.get('passing', {}).get('sacked'),
                            stats.get('passing', {}).get('passAttempts'),
                            float(stats.get('passing', {}).get('passAvg', 0)) if stats.get('passing', {}).get('passAvg') else None,
                            stats.get('passing', {}).get('passTD'),
                            stats.get('passing', {}).get('passYds'),
                            stats.get('passing', {}).get('int'),
                            stats.get('passing', {}).get('passCompletions'),
                            stats.get('defense', {}).get('defensiveInterceptionsYards'),
                            stats.get('defense', {}).get('interceptionTDs'),
                            stats.get('defense', {}).get('fumblesLost'),
                            stats.get('defense', {}).get('fumbles'),
                            stats.get('defense', {}).get('fumblesRecovered'),
                            stats.get('rushing', {}).get('rushingTwoPointConversion'),
                            stats.get('receiving', {}).get('receivingTwoPointConversion'),
                            stats.get('passing', {}).get('passingTwoPointConversion'),
                            stats.get('defense', {}).get('twoPointConversionReturn')
                        ))

                    execute_batch(cursor, """
                        INSERT INTO public.nfl_player_stats (
                            season, week, game_id, player_id, player_name, team, position,
                            defense_totaltackles, defense_deftd, defense_forcedfumbles,
                            defense_solotackles, defense_tfl, defense_qbhits,
                            defense_defensiveinterceptions, defense_sacks, defense_passdeflections,
                            kicking_kickreturns, kicking_kickreturntd, kicking_kickreturnyds,
                            kicking_kickreturnavg, kicking_kickreturnlong,
                            receiving_receptions, receiving_rectd, receiving_longrec,
                            receiving_targets, receiving_recyds, receiving_recavg,
                            rushing_rushavg, rushing_rushyds, rushing_carries,
                            rushing_longrush, rushing_rushtd,
                            kicking_fglong, kicking_fgmade, kicking_fgattempts,
                            kicking_xpmade, kicking_fgpct, kicking_kickingpts,
                            kicking_xpattempts, kicking_fgmissed, kicking_xpmissed,
                            passing_qbr, passing_rtg, passing_sacked, passing_passattempts,
                            passing_passavg, passing_passtd, passing_passyds, passing_int,
                            passing_passcompletions,
                            defense_defensiveinterceptionsyards, defense_interceptiontds,
                            defense_fumbleslost, defense_fumbles, defense_fumblesrecovered,
                            rushing_rushingtwopointconversion, receiving_receivingtwopointconversion,
                            passing_passingtwopointconversion, defense_twopointconversionreturn
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (game_id, player_id) DO UPDATE SET
                            position = COALESCE(EXCLUDED.position, nfl_player_stats.position),
                            defense_totaltackles = COALESCE(EXCLUDED.defense_totaltackles, nfl_player_stats.defense_totaltackles),
                            defense_deftd = COALESCE(EXCLUDED.defense_deftd, nfl_player_stats.defense_deftd),
                            defense_forcedfumbles = COALESCE(EXCLUDED.defense_forcedfumbles, nfl_player_stats.defense_forcedfumbles),
                            defense_solotackles = COALESCE(EXCLUDED.defense_solotackles, nfl_player_stats.defense_solotackles),
                            defense_tfl = COALESCE(EXCLUDED.defense_tfl, nfl_player_stats.defense_tfl),
                            defense_qbhits = COALESCE(EXCLUDED.defense_qbhits, nfl_player_stats.defense_qbhits),
                            defense_defensiveinterceptions = COALESCE(EXCLUDED.defense_defensiveinterceptions, nfl_player_stats.defense_defensiveinterceptions),
                            defense_sacks = COALESCE(EXCLUDED.defense_sacks, nfl_player_stats.defense_sacks),
                            defense_passdeflections = COALESCE(EXCLUDED.defense_passdeflections, nfl_player_stats.defense_passdeflections),
                            kicking_kickreturns = COALESCE(EXCLUDED.kicking_kickreturns, nfl_player_stats.kicking_kickreturns),
                            kicking_kickreturntd = COALESCE(EXCLUDED.kicking_kickreturntd, nfl_player_stats.kicking_kickreturntd),
                            kicking_kickreturnyds = COALESCE(EXCLUDED.kicking_kickreturnyds, nfl_player_stats.kicking_kickreturnyds),
                            kicking_kickreturnavg = COALESCE(EXCLUDED.kicking_kickreturnavg, nfl_player_stats.kicking_kickreturnavg),
                            kicking_kickreturnlong = COALESCE(EXCLUDED.kicking_kickreturnlong, nfl_player_stats.kicking_kickreturnlong),
                            receiving_receptions = COALESCE(EXCLUDED.receiving_receptions, nfl_player_stats.receiving_receptions),
                            receiving_rectd = COALESCE(EXCLUDED.receiving_rectd, nfl_player_stats.receiving_rectd),
                            receiving_longrec = COALESCE(EXCLUDED.receiving_longrec, nfl_player_stats.receiving_longrec),
                            receiving_targets = COALESCE(EXCLUDED.receiving_targets, nfl_player_stats.receiving_targets),
                            receiving_recyds = COALESCE(EXCLUDED.receiving_recyds, nfl_player_stats.receiving_recyds),
                            receiving_recavg = COALESCE(EXCLUDED.receiving_recavg, nfl_player_stats.receiving_recavg),
                            rushing_rushavg = COALESCE(EXCLUDED.rushing_rushavg, nfl_player_stats.rushing_rushavg),
                            rushing_rushyds = COALESCE(EXCLUDED.rushing_rushyds, nfl_player_stats.rushing_rushyds),
                            rushing_carries = COALESCE(EXCLUDED.rushing_carries, nfl_player_stats.rushing_carries),
                            rushing_longrush = COALESCE(EXCLUDED.rushing_longrush, nfl_player_stats.rushing_longrush),
                            rushing_rushtd = COALESCE(EXCLUDED.rushing_rushtd, nfl_player_stats.rushing_rushtd),
                            kicking_fglong = COALESCE(EXCLUDED.kicking_fglong, nfl_player_stats.kicking_fglong),
                            kicking_fgmade = COALESCE(EXCLUDED.kicking_fgmade, nfl_player_stats.kicking_fgmade),
                            kicking_fgattempts = COALESCE(EXCLUDED.kicking_fgattempts, nfl_player_stats.kicking_fgattempts),
                            kicking_xpmade = COALESCE(EXCLUDED.kicking_xpmade, nfl_player_stats.kicking_xpmade),
                            kicking_fgpct = COALESCE(EXCLUDED.kicking_fgpct, nfl_player_stats.kicking_fgpct),
                            kicking_kickingpts = COALESCE(EXCLUDED.kicking_kickingpts, nfl_player_stats.kicking_kickingpts),
                            kicking_xpattempts = COALESCE(EXCLUDED.kicking_xpattempts, nfl_player_stats.kicking_xpattempts),
                            kicking_fgmissed = COALESCE(EXCLUDED.kicking_fgmissed, nfl_player_stats.kicking_fgmissed),
                            kicking_xpmissed = COALESCE(EXCLUDED.kicking_xpmissed, nfl_player_stats.kicking_xpmissed),
                            passing_qbr = COALESCE(EXCLUDED.passing_qbr, nfl_player_stats.passing_qbr),
                            passing_rtg = COALESCE(EXCLUDED.passing_rtg, nfl_player_stats.passing_rtg),
                            passing_sacked = COALESCE(EXCLUDED.passing_sacked, nfl_player_stats.passing_sacked),
                            passing_passattempts = COALESCE(EXCLUDED.passing_passattempts, nfl_player_stats.passing_passattempts),
                            passing_passavg = COALESCE(EXCLUDED.passing_passavg, nfl_player_stats.passing_passavg),
                            passing_passtd = COALESCE(EXCLUDED.passing_passtd, nfl_player_stats.passing_passtd),
                            passing_passyds = COALESCE(EXCLUDED.passing_passyds, nfl_player_stats.passing_passyds),
                            passing_int = COALESCE(EXCLUDED.passing_int, nfl_player_stats.passing_int),
                            passing_passcompletions = COALESCE(EXCLUDED.passing_passcompletions, nfl_player_stats.passing_passcompletions),
                            defense_defensiveinterceptionsyards = COALESCE(EXCLUDED.defense_defensiveinterceptionsyards, nfl_player_stats.defense_defensiveinterceptionsyards),
                            defense_interceptiontds = COALESCE(EXCLUDED.defense_interceptiontds, nfl_player_stats.defense_interceptiontds),
                            defense_fumbleslost = COALESCE(EXCLUDED.defense_fumbleslost, nfl_player_stats.defense_fumbleslost),
                            defense_fumbles = COALESCE(EXCLUDED.defense_fumbles, nfl_player_stats.defense_fumbles),
                            defense_fumblesrecovered = COALESCE(EXCLUDED.defense_fumblesrecovered, nfl_player_stats.defense_fumblesrecovered),
                            rushing_rushingtwopointconversion = COALESCE(EXCLUDED.rushing_rushingtwopointconversion, nfl_player_stats.rushing_rushingtwopointconversion),
                            receiving_receivingtwopointconversion = COALESCE(EXCLUDED.receiving_receivingtwopointconversion, nfl_player_stats.receiving_receivingtwopointconversion),
                            passing_passingtwopointconversion = COALESCE(EXCLUDED.passing_passingtwopointconversion, nfl_player_stats.passing_passingtwopointconversion),
                            defense_twopointconversionreturn = COALESCE(EXCLUDED.defense_twopointconversionreturn, nfl_player_stats.defense_twopointconversionreturn)
                    """, player_data)
                    conn.commit()
                    print(f"nfl_player_stats: {len(player_data)} rows inserted")
            except Exception as e:
                conn.rollback()
                print(f"Error in nfl_player_stats: {e}")

            # ---------------- nfl_team_stats ----------------
            try:
                team_stats = data.get('team_stats', [])
                if team_stats:
                    team_data = []
                    opponent_map = {team['team_abv']: team['opponent'] for team in team_stats if 'opponent' in team}
                    for team in team_stats:
                        location = 'home' if team['team_abv'] == game_info['home_team'] else 'away'
                        if game_info.get('neutral_site', False):
                            location = 'neutral'
                        team_data.append((
                            season,
                            week,
                            game_id,
                            team['team_abv'],
                            team['total_yards'],
                            team['passing_yards'],
                            team['rushing_yards'],
                            team['turnovers'],
                            None, None, None,  # op_ columns filled in later
                            game_info['home_pts'] if team['team_abv'] == game_info['home_team'] else game_info['away_pts'],
                            game_info['away_pts'] if team['team_abv'] == game_info['home_team'] else game_info['home_pts'],
                            opponent_map.get(team['team_abv']),
                            location
                        ))
                    execute_batch(cursor, """
                        INSERT INTO public.nfl_team_stats (
                            season, week, game_id, team, total_yards, passing_yards,
                            rushing_yards, turnovers, op_passing_yards, op_rushing_yards,
                            op_total_yards, points, op_points, opponent, location
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (season, week, game_id, team) DO UPDATE SET
                            total_yards = EXCLUDED.total_yards,
                            passing_yards = EXCLUDED.passing_yards,
                            rushing_yards = EXCLUDED.rushing_yards,
                            turnovers = EXCLUDED.turnovers,
                            points = EXCLUDED.points,
                            op_points = EXCLUDED.op_points,
                            opponent = EXCLUDED.opponent,
                            location = EXCLUDED.location
                    """, team_data)
                    conn.commit()
                    print(f"nfl_team_stats: {len(team_data)} rows inserted")
            except Exception as e:
                conn.rollback()
                print(f"Error in nfl_team_stats: {e}")

            # ---------------- nfl_scoring_plays ----------------
            try:
                scoring_plays = data.get('scoring_plays', [])
                if scoring_plays:
                    scoring_data = []
                    for play in scoring_plays:
                        scoring_data.append((
                            season,
                            week,
                            game_id,
                            play['period'],
                            play['time'],
                            play['team'],
                            play['type'],
                            play['details'],
                            play['points']
                        ))
                    execute_batch(cursor, """
                        INSERT INTO public.nfl_scoring_plays (
                            season, week, game_id, period, time, team, type, details, points
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, scoring_data)
                    conn.commit()
                    print(f"nfl_scoring_plays: {len(scoring_data)} rows inserted")
            except Exception as e:
                conn.rollback()
                print(f"Error in nfl_scoring_plays: {e}")

            # ---------------- nfl_season_dst_stats ----------------
            try:
                dst_stats = data.get('dst_stats', [])
                if dst_stats:
                    dst_data = []
                    for dst in dst_stats:
                        dst_data.append((
                            season,
                            week,
                            game_id,
                            dst['team'],
                            dst['team_abv'],
                            dst['sacks'],
                            dst['interceptions'],
                            dst['points_allowed']
                        ))
                    execute_batch(cursor, """
                        INSERT INTO public.nfl_season_dst_stats (
                            season, week, game_id, team, team_abv, sacks, interceptions, points_allowed
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (game_id, team_abv, team) DO UPDATE SET
                            sacks = EXCLUDED.sacks,
                            interceptions = EXCLUDED.interceptions,
                            points_allowed = EXCLUDED.points_allowed
                    """, dst_data)
                    conn.commit()
                    print(f"nfl_season_dst_stats: {len(dst_data)} rows inserted")
            except Exception as e:
                conn.rollback()
                print(f"Error in nfl_season_dst_stats: {e}")

        return {'statusCode': 200, 'body': 'Boxscore data processed successfully'}

    except Exception as e:
        print(f"Error processing boxscore: {str(e)}")
        if conn:
            conn.rollback()
        return {'statusCode': 500, 'body': f'Error processing boxscore: {str(e)}'}
    finally:
        if conn:
            conn.close()
