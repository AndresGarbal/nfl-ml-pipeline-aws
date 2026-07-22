from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import pandas as pd
import os
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import RobustScaler
import warnings

warnings.filterwarnings('ignore')

def convert_numpy_types(value):
    """Convert numpy types to native Python types for PostgreSQL compatibility"""
    if isinstance(value, (np.integer, np.int64, np.int32)):
        return int(value)
    elif isinstance(value, (np.floating, np.float64, np.float32)):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    elif isinstance(value, np.ndarray):
        return value.tolist()
    elif pd.isna(value) or value is None:
        return None
    else:
        return value

def prepare_db_params(params_dict):
    """Prepare DB parameters by converting numpy types"""
    return {key: convert_numpy_types(value) for key, value in params_dict.items()}

class NFLDynamic2025System:
    """Dynamic NFL system for the full 2025 season with database management"""
    
    def __init__(self):
        self.engine = None
        self.dfT = None
        self.dfR = None  
        self.dfS = None
        self.dfT_features = None
        self.matchup_data = None
        self.models = {}
        self.scalers = {}
        self.feature_cols = []
        self.training_results = {}
        self.team_2024_stats = {}
        self.current_season = 2025
        self.max_available_week = 0
        
        print("DYNAMIC NFL SYSTEM 2025 - OPTIMIZED VERSION (ELASTICNET)")
        print("Automatic week and database management")
    
    def connect_database(self):
        """Connect and load data"""
        print("Connecting to database...")
        
        load_dotenv()
        
        DB_NAME = os.getenv("DB_NAME")
        DB_HOST = os.getenv("DB_HOST")
        DB_PASS = os.getenv("DB_PASS")
        DB_PORT = os.getenv("DB_PORT", "5433")
        DB_USER = os.getenv("DB_USER")
        
        self.engine = create_engine(
            f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}",
            connect_args={'connect_timeout': 10}
        )
        
        try:
            with self.engine.connect() as conn:
                self.dfT = pd.read_sql(text("SELECT * FROM nfl_team_stats WHERE season >= 2023"), conn)
                self.dfR = pd.read_sql(text("SELECT * FROM rankings WHERE season >= 2023"), conn)
                self.dfS = pd.read_sql(text("SELECT * FROM nfl_schedules WHERE season >= 2023"), conn)
                
                # Detect the last available week
                current_season_data = self.dfT[self.dfT['season'] == self.current_season]
                if not current_season_data.empty:
                    self.max_available_week = int(current_season_data['week'].max())  # Convert to int
                    print(f"Last week with data in {self.current_season}: {self.max_available_week}")
                else:
                    self.max_available_week = 0
                    print(f"No data for {self.current_season} - predictions only from week 1")
                
                seasons_available = sorted(self.dfT['season'].unique())
                print(f"Data loaded - Seasons: {seasons_available}")
                
                return True
                
        except Exception as e:
            print(f"Error loading data: {e}")
            return False
    
    def create_database_tables(self):
        """Create the required tables if they do not exist"""
        print("Verifying and creating required tables...")
        
        try:
            with self.engine.connect() as conn:
                # game_predictions table
                create_game_predictions = """
                CREATE TABLE IF NOT EXISTS game_predictions (
                    id SERIAL PRIMARY KEY,
                    game_id VARCHAR(100) UNIQUE,
                    season INTEGER,
                    week INTEGER,
                    gameday VARCHAR(50),
                    away_team VARCHAR(10),
                    home_team VARCHAR(10),
                    
                    -- Predictions
                    predicted_winner VARCHAR(10),
                    away_predicted_points NUMERIC(5,2),
                    home_predicted_points NUMERIC(5,2),
                    away_predicted_total_yards NUMERIC(6,2),
                    home_predicted_total_yards NUMERIC(6,2),
                    away_predicted_passing_yards NUMERIC(6,2),
                    home_predicted_passing_yards NUMERIC(6,2),
                    away_predicted_rushing_yards NUMERIC(6,2),
                    home_predicted_rushing_yards NUMERIC(6,2),
                    point_differential NUMERIC(5,2),
                    confidence NUMERIC(4,3),
                    
                    -- Actual results (when available)
                    away_actual_points NUMERIC(5,2),
                    home_actual_points NUMERIC(5,2),
                    away_actual_total_yards NUMERIC(6,2),
                    home_actual_total_yards NUMERIC(6,2),
                    away_actual_passing_yards NUMERIC(6,2),
                    home_actual_passing_yards NUMERIC(6,2),
                    away_actual_rushing_yards NUMERIC(6,2),
                    home_actual_rushing_yards NUMERIC(6,2),
                    actual_winner VARCHAR(10),
                    
                    -- Differences
                    points_diff_away NUMERIC(5,2),
                    points_diff_home NUMERIC(5,2),
                    total_yards_diff_away NUMERIC(6,2),
                    total_yards_diff_home NUMERIC(6,2),
                    passing_yards_diff_away NUMERIC(6,2),
                    passing_yards_diff_home NUMERIC(6,2),
                    rushing_yards_diff_away NUMERIC(6,2),
                    rushing_yards_diff_home NUMERIC(6,2),
                    winner_prediction_correct BOOLEAN,
                    
                    -- Metadata
                    data_source VARCHAR(50),
                    prediction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
                
                # week_game_results table
                create_week_results = """
                CREATE TABLE IF NOT EXISTS week_game_results (
                    id SERIAL PRIMARY KEY,
                    season INTEGER,
                    week INTEGER,
                    total_games INTEGER,
                    games_with_results INTEGER,
                    correct_predictions INTEGER,
                    incorrect_predictions INTEGER,
                    accuracy NUMERIC(5,3),
                    avg_points_error NUMERIC(5,2),
                    avg_total_yards_error NUMERIC(6,2),
                    avg_passing_yards_error NUMERIC(6,2),
                    avg_rushing_yards_error NUMERIC(6,2),
                    high_confidence_games INTEGER,
                    high_confidence_correct INTEGER,
                    high_confidence_accuracy NUMERIC(5,3),
                    close_games_predicted INTEGER,
                    close_games_actual INTEGER,
                    blowout_games_predicted INTEGER,
                    blowout_games_actual INTEGER,
                    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(season, week)
                );
                """
                
                conn.execute(text(create_game_predictions))
                conn.execute(text(create_week_results))
                conn.commit()
                
                print("Tables verified/created successfully")
                return True
                
        except Exception as e:
            print(f"Error creating tables: {e}")
            return False
    
    def get_next_prediction_week(self):
        """Determine which week to predict next"""
        if self.max_available_week == 0:
            return 1
        else:
            return self.max_available_week + 1
    
    def create_advanced_features(self):
        """Create advanced features for all seasons"""
        print("Creating advanced features...")
        
        self.dfT_features = self.dfT.sort_values(['team', 'season', 'week']).copy()
        
        base_metrics = ['total_yards', 'passing_yards', 'rushing_yards', 'points', 
                       'turnovers', 'op_total_yards', 'op_passing_yards', 
                       'op_rushing_yards', 'op_points']
        
        windows = [3, 4, 6]
        
        for window in windows:
            for metric in base_metrics:
                self.dfT_features[f'{metric}_avg_{window}'] = (
                    self.dfT_features.groupby(['team', 'season'])[metric]
                    .rolling(window=window, min_periods=1)
                    .mean()
                    .reset_index(level=[0, 1], drop=True)
                )
                
                self.dfT_features[f'{metric}_std_{window}'] = (
                    self.dfT_features.groupby(['team', 'season'])[metric]
                    .rolling(window=window, min_periods=1)
                    .std()
                    .reset_index(level=[0, 1], drop=True)
                ).fillna(0)
                
                self.dfT_features[f'{metric}_trend_{window}'] = (
                    self.dfT_features.groupby(['team', 'season'])[f'{metric}_avg_{window}']
                    .diff(1)
                    .fillna(0)
                )
        
        # Efficiency features
        self.dfT_features['offensive_efficiency'] = (
            self.dfT_features['points'] / (self.dfT_features['total_yards'] + 1)
        )
        
        self.dfT_features['pass_rush_ratio'] = (
            self.dfT_features['passing_yards'] / (self.dfT_features['rushing_yards'] + 1)
        )
        
        self.dfT_features['recent_points_avg'] = (
            self.dfT_features.groupby(['team', 'season'])['points']
            .rolling(window=2, min_periods=1)
            .mean()
            .reset_index(level=[0, 1], drop=True)
        )
        
        print(f"Features created. Total columns: {len(self.dfT_features.columns)}")
    
    def create_defensive_factors(self):
        """Create defensive factors"""
        def rank_to_factor(rank, total_teams=32):
            if pd.isna(rank):
                return 0.5
            normalized = (total_teams - rank) / (total_teams - 1)
            return normalized ** 0.8
        
        rank_to_factor_map = {
            'op_total_yards_rank': 'op_total_yards_factor',
            'op_points_rank': 'op_points_factor'
        }
        
        for rank_col, factor_col in rank_to_factor_map.items():
            if rank_col in self.dfR.columns:
                self.dfR[factor_col] = self.dfR[rank_col].apply(rank_to_factor)
    
    def calculate_2024_final_stats(self):
        """Compute final 2024 statistics"""
        print("Computing final 2024 statistics...")
        
        teams_2024 = self.dfT_features[self.dfT_features['season'] == 2024]['team'].unique()
        
        for team in teams_2024:
            team_data = self.dfT_features[
                (self.dfT_features['team'] == team) & 
                (self.dfT_features['season'] == 2024)
            ].sort_values('week')
            
            if not team_data.empty:
                final_stats = team_data.tail(1).iloc[0]
                self.team_2024_stats[team] = final_stats
        
        print(f"2024 statistics computed for {len(self.team_2024_stats)} teams")
    
    def create_matchup_data(self):
        """Create training data using 2023-2024"""
        print("Creating training data...")
        
        matchups = []
        
        training_games = self.dfS[
            (self.dfS['season'] >= 2023) &
            (pd.notna(self.dfS['away_score'])) & 
            (pd.notna(self.dfS['home_score']))
        ]
        
        for _, game in training_games.iterrows():
            away_stats = self.dfT_features[
                (self.dfT_features['team'] == game['away_team']) & 
                (self.dfT_features['season'] == game['season']) & 
                (self.dfT_features['week'] < game['week'])
            ].tail(1)
            
            home_stats = self.dfT_features[
                (self.dfT_features['team'] == game['home_team']) & 
                (self.dfT_features['season'] == game['season']) & 
                (self.dfT_features['week'] < game['week'])
            ].tail(1)
            
            if away_stats.empty:
                away_stats = self.dfT_features[
                    (self.dfT_features['team'] == game['away_team']) & 
                    (self.dfT_features['season'] == game['season']) & 
                    (self.dfT_features['week'] == game['week'])
                ].head(1)
            
            if home_stats.empty:
                home_stats = self.dfT_features[
                    (self.dfT_features['team'] == game['home_team']) & 
                    (self.dfT_features['season'] == game['season']) & 
                    (self.dfT_features['week'] == game['week'])
                ].head(1)
            
            if away_stats.empty or home_stats.empty:
                continue
            
            away_def = self.dfR[
                (self.dfR['team'] == game['away_team']) & 
                (self.dfR['season'] == game['season']) & 
                (self.dfR['week'] <= game['week'])
            ].tail(1)
            
            home_def = self.dfR[
                (self.dfR['team'] == game['home_team']) & 
                (self.dfR['season'] == game['season']) & 
                (self.dfR['week'] <= game['week'])
            ].tail(1)
            
            if away_def.empty or home_def.empty:
                continue
            
            away_actual = self.dfT_features[
                (self.dfT_features['team'] == game['away_team']) & 
                (self.dfT_features['season'] == game['season']) & 
                (self.dfT_features['week'] == game['week'])
            ]
            
            home_actual = self.dfT_features[
                (self.dfT_features['team'] == game['home_team']) & 
                (self.dfT_features['season'] == game['season']) & 
                (self.dfT_features['week'] == game['week'])
            ]
            
            if away_actual.empty or home_actual.empty:
                continue
            
            for team_type in ['away', 'home']:
                is_home = 1 if team_type == 'home' else 0
                
                if team_type == 'away':
                    team_stats = away_stats.iloc[0]
                    opp_def = home_def.iloc[0]
                    actual_stats = away_actual.iloc[0]
                    actual_points = game['away_score']
                else:
                    team_stats = home_stats.iloc[0]
                    opp_def = away_def.iloc[0]
                    actual_stats = home_actual.iloc[0]
                    actual_points = game['home_score']
                
                matchup = {
                    'season': game['season'],
                    'week': game['week'],
                    'is_home': is_home,
                    
                    'team_points_avg_3': team_stats.get('points_avg_3', 24),
                    'team_points_avg_4': team_stats.get('points_avg_4', 24),
                    'team_points_avg_6': team_stats.get('points_avg_6', 24),
                    'team_total_yards_avg_3': team_stats.get('total_yards_avg_3', 350),
                    'team_total_yards_avg_4': team_stats.get('total_yards_avg_4', 350),
                    'team_total_yards_avg_6': team_stats.get('total_yards_avg_6', 350),
                    'team_passing_yards_avg_4': team_stats.get('passing_yards_avg_4', 230),
                    'team_rushing_yards_avg_4': team_stats.get('rushing_yards_avg_4', 120),
                    'team_points_std_4': team_stats.get('points_std_4', 7),
                    'team_total_yards_std_4': team_stats.get('total_yards_std_4', 50),
                    'team_points_trend_4': team_stats.get('points_trend_4', 0),
                    'team_total_yards_trend_4': team_stats.get('total_yards_trend_4', 0),
                    'team_off_efficiency': team_stats.get('offensive_efficiency', 0.07),
                    'team_pass_rush_ratio': team_stats.get('pass_rush_ratio', 2.0),
                    'team_recent_points': team_stats.get('recent_points_avg', 24),
                    
                    'opp_def_total_rank': opp_def.get('op_total_yards_rank', 16),
                    'opp_def_passing_rank': opp_def.get('op_passing_yards_rank', 16),
                    'opp_def_rushing_rank': opp_def.get('op_rushing_yards_rank', 16),
                    'opp_def_points_rank': opp_def.get('op_points_rank', 16),
                    'opp_def_total_factor': opp_def.get('op_total_yards_factor', 0.5),
                    'opp_def_points_factor': opp_def.get('op_points_factor', 0.5),
                    
                    'actual_total_yards': actual_stats.get('total_yards', 350),
                    'actual_passing_yards': actual_stats.get('passing_yards', 230),
                    'actual_rushing_yards': actual_stats.get('rushing_yards', 120),
                    'actual_points': actual_points
                }
                
                matchups.append(matchup)
        
        self.matchup_data = pd.DataFrame(matchups)
        print(f"Training data: {len(self.matchup_data)} records")
    
    def train_models(self):
        """Train models using ElasticNet only"""
        print("Training models with ElasticNet...")
        
        metrics = {
            'total_yards': 'actual_total_yards',
            'passing_yards': 'actual_passing_yards', 
            'rushing_yards': 'actual_rushing_yards',
            'points': 'actual_points'
        }
        
        self.feature_cols = [
            'season', 'week', 'is_home',
            'team_points_avg_3', 'team_points_avg_4', 'team_points_avg_6',
            'team_total_yards_avg_3', 'team_total_yards_avg_4', 'team_total_yards_avg_6',
            'team_passing_yards_avg_4', 'team_rushing_yards_avg_4',
            'team_points_std_4', 'team_total_yards_std_4',
            'team_points_trend_4', 'team_total_yards_trend_4',
            'team_off_efficiency', 'team_pass_rush_ratio', 'team_recent_points',
            'opp_def_total_rank', 'opp_def_passing_rank', 
            'opp_def_rushing_rank', 'opp_def_points_rank',
            'opp_def_total_factor', 'opp_def_points_factor'
        ]
        
        for metric_name, target_col in metrics.items():
            print(f"  Training {metric_name}...")
            
            df_clean = self.matchup_data.dropna(subset=[target_col] + self.feature_cols)
            X = df_clean[self.feature_cols]
            y = df_clean[target_col]
            
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42,
                stratify=df_clean['is_home']
            )
            
            # ElasticNet only, with RobustScaler
            scaler = RobustScaler()
            model = ElasticNet(alpha=0.1, l1_ratio=0.5, random_state=42)
            
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            model.fit(X_train_scaled, y_train)
            y_pred = model.predict(X_test_scaled)
            
            # Save model and scaler
            self.models[metric_name] = model
            self.scalers[metric_name] = scaler
            
            # Metrics
            mae = mean_absolute_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)
            
            self.training_results[metric_name] = {
                'model': 'ElasticNet',
                'mae': mae,
                'r2': r2
            }
            
            print(f"    ElasticNet - MAE: {mae:.2f}, R²: {r2:.3f}")
    
    def get_team_current_stats(self, team, target_week, season=2025):
        """Get the team's current stats for prediction"""
        if target_week == 1:
            # Week 1: use final 2024 stats
            if team in self.team_2024_stats:
                return self.team_2024_stats[team]
            else:
                print(f"Warning: No 2024 stats for {team}")
                return None
        else:
            # Weeks 2+: use most recent 2025 stats
            team_stats_2025 = self.dfT_features[
                (self.dfT_features['team'] == team) & 
                (self.dfT_features['season'] == season) & 
                (self.dfT_features['week'] < target_week)
            ].tail(1)
            
            if not team_stats_2025.empty:
                return team_stats_2025.iloc[0]
            else:
                # Fall back to 2024 stats if there is no 2025 data
                print(f"Warning: No 2025 stats for {team} week {target_week}, using 2024")
                if team in self.team_2024_stats:
                    return self.team_2024_stats[team]
                else:
                    return None
    
    def get_team_defensive_stats(self, team, target_week, season=2025):
        """Get the team's defensive stats"""
        if target_week == 1:
            # Week 1: use final 2024 rankings
            def_stats = self.dfR[
                (self.dfR['team'] == team) & 
                (self.dfR['season'] == 2024)
            ].tail(1)
        else:
            # Weeks 2+: use most recent 2025 rankings
            def_stats = self.dfR[
                (self.dfR['team'] == team) & 
                (self.dfR['season'] == season) & 
                (self.dfR['week'] < target_week)
            ].tail(1)
            
            # Fall back to 2024 if there is no 2025 data
            if def_stats.empty:
                def_stats = self.dfR[
                    (self.dfR['team'] == team) & 
                    (self.dfR['season'] == 2024)
                ].tail(1)
        
        return def_stats if not def_stats.empty else None
    
    def predict_dynamic_game(self, away_team, home_team, week, season=2025, show_details=False):
        """Predict any 2025 game"""
        if show_details:
            print(f"Predicting: {away_team} @ {home_team} (S{season} W{week})")
            if week == 1:
                print("  Using final 2024 stats")
            else:
                print(f"  Using prior 2025 stats (through week {week-1})")
        
        # Get each team's current stats
        away_stats = self.get_team_current_stats(away_team, week, season)
        home_stats = self.get_team_current_stats(home_team, week, season)
        
        if away_stats is None or home_stats is None:
            print(f"Cannot get stats for {away_team} or {home_team}")
            return None
        
        # Get defensive stats
        away_def = self.get_team_defensive_stats(away_team, week, season)
        home_def = self.get_team_defensive_stats(home_team, week, season)
        
        if away_def is None or home_def is None:
            print(f"Cannot get defensive stats")
            return None
        
        # Prepare features for prediction
        def prepare_features(team_stats, opp_def, is_home):
            if hasattr(team_stats, 'get'):
                stats = team_stats
            else:
                stats = team_stats.to_dict() if hasattr(team_stats, 'to_dict') else team_stats
            
            def_data = opp_def.iloc[0] if hasattr(opp_def, 'iloc') else opp_def
            
            return {
                'season': season,
                'week': week,
                'is_home': is_home,
                'team_points_avg_3': stats.get('points_avg_3', 24),
                'team_points_avg_4': stats.get('points_avg_4', 24),
                'team_points_avg_6': stats.get('points_avg_6', 24),
                'team_total_yards_avg_3': stats.get('total_yards_avg_3', 350),
                'team_total_yards_avg_4': stats.get('total_yards_avg_4', 350),
                'team_total_yards_avg_6': stats.get('total_yards_avg_6', 350),
                'team_passing_yards_avg_4': stats.get('passing_yards_avg_4', 230),
                'team_rushing_yards_avg_4': stats.get('rushing_yards_avg_4', 120),
                'team_points_std_4': stats.get('points_std_4', 7),
                'team_total_yards_std_4': stats.get('total_yards_std_4', 50),
                'team_points_trend_4': stats.get('points_trend_4', 0),
                'team_total_yards_trend_4': stats.get('total_yards_trend_4', 0),
                'team_off_efficiency': stats.get('offensive_efficiency', 0.07),
                'team_pass_rush_ratio': stats.get('pass_rush_ratio', 2.0),
                'team_recent_points': stats.get('recent_points_avg', 24),
                'opp_def_total_rank': def_data.get('op_total_yards_rank', 16),
                'opp_def_passing_rank': def_data.get('op_passing_yards_rank', 16),
                'opp_def_rushing_rank': def_data.get('op_rushing_yards_rank', 16),
                'opp_def_points_rank': def_data.get('op_points_rank', 16),
                'opp_def_total_factor': def_data.get('op_total_yards_factor', 0.5),
                'opp_def_points_factor': def_data.get('op_points_factor', 0.5)
            }
        
        away_features = prepare_features(away_stats, home_def, 0)
        home_features = prepare_features(home_stats, away_def, 1)
        
        # Make predictions using trained models
        metrics = ['total_yards', 'passing_yards', 'rushing_yards', 'points']
        away_predictions = {}
        home_predictions = {}
        
        for metric in metrics:
            if metric not in self.models:
                continue
            
            model = self.models[metric]
            scaler = self.scalers[metric]
            
            # Away team
            away_X = pd.DataFrame([away_features])[self.feature_cols]
            away_pred = model.predict(scaler.transform(away_X))[0]
            
            # Apply defensive adjustments
            adjustment_factors = {'total_yards': 0.18, 'passing_yards': 0.22, 'rushing_yards': 0.20, 'points': 0.15}
            factor = adjustment_factors.get(metric, 0.15)
            
            if metric == 'total_yards':
                def_factor = away_features['opp_def_total_factor']
            elif metric == 'points':
                def_factor = away_features['opp_def_points_factor']
            else:
                def_factor = away_features['opp_def_total_factor']
            
            def_adjustment = (def_factor - 0.5) * factor
            efficiency_adjustment = (away_features['team_off_efficiency'] - 0.07) * 0.1
            total_adjustment = away_pred * (def_adjustment + efficiency_adjustment)
            
            away_predictions[metric] = max(0, away_pred + total_adjustment)
            
            # Home team (same process + home advantage)
            home_X = pd.DataFrame([home_features])[self.feature_cols]
            home_pred = model.predict(scaler.transform(home_X))[0]
            
            if metric == 'total_yards':
                def_factor = home_features['opp_def_total_factor']
            elif metric == 'points':
                def_factor = home_features['opp_def_points_factor']
            else:
                def_factor = home_features['opp_def_total_factor']
            
            def_adjustment = (def_factor - 0.5) * factor
            efficiency_adjustment = (home_features['team_off_efficiency'] - 0.07) * 0.1
            total_adjustment = home_pred * (def_adjustment + efficiency_adjustment)
            
            home_final = home_pred + total_adjustment
            
            # Home advantage
            if metric == 'points':
                home_final += 2.8
            elif metric == 'total_yards':
                home_final += 8
            
            home_predictions[metric] = max(0, home_final)
        
        # Determine winner and confidence
        away_points = away_predictions.get('points', 0)
        home_points = home_predictions.get('points', 0)
        
        winner = 'home' if home_points > away_points else 'away'
        point_diff = abs(home_points - away_points)
        confidence = min(point_diff / 16.0, 1.0)
        
        if show_details:
            print(f"  {away_team}: {away_points:.1f} pts")
            print(f"  {home_team}: {home_points:.1f} pts")
            print(f"  Winner: {winner.upper()}, Confidence: {confidence:.2f}")
        
        return {
            'away_team': away_team,
            'home_team': home_team,
            'week': week,
            'season': season,
            'away_predictions': away_predictions,
            'home_predictions': home_predictions,
            'predicted_winner': winner,
            'point_differential': point_diff,
            'confidence': confidence,
            'data_source': 'stats_2024' if week == 1 else f'stats_2025_w{week-1}'
        }
    
    def save_new_predictions_to_database(self, predictions):
        """Save ONLY new predictions to the database (without actual results)"""
        if not predictions:
            return None

        print(f"Saving {len(predictions)} new predictions to the database...")

        try:
            with self.engine.connect() as conn:
                for pred in predictions:
                    game_id = f"{pred['season']}_W{pred['week']}_{pred['away_team']}_{pred['home_team']}"

                    # Check if it already exists
                    check_query = text("""
                        SELECT id FROM game_predictions 
                        WHERE game_id = :game_id
                    """)
                    existing = conn.execute(check_query, {"game_id": game_id}).fetchone()

                    if existing:
                        # Update predictions only (leave actual results untouched)
                        update_query = text("""
                            UPDATE game_predictions SET
                                away_predicted_points = :away_pred_pts,
                                home_predicted_points = :home_pred_pts,
                                away_predicted_total_yards = :away_pred_yds,
                                home_predicted_total_yards = :home_pred_yds,
                                away_predicted_passing_yards = :away_pred_pass,
                                home_predicted_passing_yards = :home_pred_pass,
                                away_predicted_rushing_yards = :away_pred_rush,
                                home_predicted_rushing_yards = :home_pred_rush,
                                predicted_winner = :pred_winner,
                                point_differential = :point_diff,
                                confidence = :confidence,
                                data_source = :data_source,
                                updated_date = CURRENT_TIMESTAMP
                            WHERE game_id = :game_id
                        """)
                    else:
                        # Insert new record (predictions only)
                        update_query = text("""
                            INSERT INTO game_predictions (
                                game_id, season, week, away_team, home_team,
                                away_predicted_points, home_predicted_points,
                                away_predicted_total_yards, home_predicted_total_yards,
                                away_predicted_passing_yards, home_predicted_passing_yards,
                                away_predicted_rushing_yards, home_predicted_rushing_yards,
                                predicted_winner, point_differential, confidence, data_source
                            ) VALUES (
                                :game_id, :season, :week, :away_team, :home_team,
                                :away_pred_pts, :home_pred_pts,
                                :away_pred_yds, :home_pred_yds,
                                :away_pred_pass, :home_pred_pass,
                                :away_pred_rush, :home_pred_rush,
                                :pred_winner, :point_diff, :confidence, :data_source
                            )
                        """)

                    # Prepare parameters (predictions only)
                    params = {
                        'game_id': game_id,
                        'season': int(pred['season']),
                        'week': int(pred['week']),
                        'away_team': pred['away_team'],
                        'home_team': pred['home_team'],
                        'away_pred_pts': float(pred['away_predictions']['points']),
                        'home_pred_pts': float(pred['home_predictions']['points']),
                        'away_pred_yds': float(pred['away_predictions']['total_yards']),
                        'home_pred_yds': float(pred['home_predictions']['total_yards']),
                        'away_pred_pass': float(pred['away_predictions']['passing_yards']),
                        'home_pred_pass': float(pred['home_predictions']['passing_yards']),
                        'away_pred_rush': float(pred['away_predictions']['rushing_yards']),
                        'home_pred_rush': float(pred['home_predictions']['rushing_yards']),
                        'pred_winner': pred['predicted_winner'],
                        'point_diff': float(pred['point_differential']),
                        'confidence': float(pred['confidence']),
                        'data_source': pred['data_source']
                    }

                    # Convert numpy types
                    params = prepare_db_params(params)
                    conn.execute(update_query, params)

                conn.commit()
                print("New predictions saved successfully")
                return True

        except Exception as e:
            print(f"Error saving new predictions: {e}")
            return False
    
    def update_past_weeks_with_results(self, current_week, season=2025):
        """Update the previous week with actual results if available"""
        if current_week <= 1:
            print("No previous weeks to update")
            return True
        
        previous_week = current_week - 1
        print(f"Checking week {previous_week} to update with actual results...")
        
        try:
            with self.engine.connect() as conn:
                # Get the previous week's predictions
                prev_predictions_query = text("""
                    SELECT * FROM game_predictions 
                    WHERE season = :season AND week = :week
                    AND away_actual_points IS NULL
                """)
                
                params = prepare_db_params({"season": season, "week": previous_week})
                prev_predictions = pd.read_sql(prev_predictions_query, conn, params=params)
                
                if prev_predictions.empty:
                    print(f"No pending predictions to update for week {previous_week}")
                    return True
                
                # Check for available actual results in nfl_team_stats
                available_teams = self.dfT_features[
                    (self.dfT_features['season'] == season) &
                    (self.dfT_features['week'] == previous_week)
                ]['team'].unique()
                
                if len(available_teams) == 0:
                    print(f"No team stats for week {previous_week}")
                    return True
                
                # Check that we have ALL required teams
                unique_teams_in_predictions = set()
                for _, pred in prev_predictions.iterrows():
                    unique_teams_in_predictions.add(pred['away_team'])
                    unique_teams_in_predictions.add(pred['home_team'])
                
                teams_with_stats = len(available_teams)
                teams_needed = len(unique_teams_in_predictions)
                
                if teams_with_stats < teams_needed:
                    print(f"WARNING: All teams are required for week {previous_week}")
                    print(f"Teams with stats: {teams_with_stats}, Teams needed: {teams_needed}")
                    print("Information not found for all teams")
                    return False
                
                print(f"Updating {len(prev_predictions)} games from week {previous_week} with actual results")
                
                # Update each game
                updates_count = 0
                for _, pred_row in prev_predictions.iterrows():
                    # Look up actual stats for each team
                    away_actual_stats = self.dfT_features[
                        (self.dfT_features['team'] == pred_row['away_team']) &
                        (self.dfT_features['season'] == season) &
                        (self.dfT_features['week'] == previous_week)
                    ]
                    
                    home_actual_stats = self.dfT_features[
                        (self.dfT_features['team'] == pred_row['home_team']) &
                        (self.dfT_features['season'] == season) &
                        (self.dfT_features['week'] == previous_week)
                    ]
                    
                    if away_actual_stats.empty or home_actual_stats.empty:
                        print(f"No stats for {pred_row['away_team']} or {pred_row['home_team']}")
                        continue
                    
                    # Get actual points from nfl_team_stats
                    away_actual_points = away_actual_stats.iloc[0]['points']
                    home_actual_points = home_actual_stats.iloc[0]['points']
                    actual_winner = 'away' if away_actual_points > home_actual_points else 'home'
                    
                    # Update database
                    update_query = text("""
                        UPDATE game_predictions SET
                            away_actual_points = :away_actual_pts,
                            home_actual_points = :home_actual_pts,
                            away_actual_total_yards = :away_actual_yds,
                            home_actual_total_yards = :home_actual_yds,
                            away_actual_passing_yards = :away_actual_pass,
                            home_actual_passing_yards = :home_actual_pass,
                            away_actual_rushing_yards = :away_actual_rush,
                            home_actual_rushing_yards = :home_actual_rush,
                            actual_winner = :actual_winner,
                            points_diff_away = :pts_diff_away,
                            points_diff_home = :pts_diff_home,
                            total_yards_diff_away = :yds_diff_away,
                            total_yards_diff_home = :yds_diff_home,
                            passing_yards_diff_away = :pass_diff_away,
                            passing_yards_diff_home = :pass_diff_home,
                            rushing_yards_diff_away = :rush_diff_away,
                            rushing_yards_diff_home = :rush_diff_home,
                            winner_prediction_correct = :winner_correct,
                            updated_date = CURRENT_TIMESTAMP
                        WHERE game_id = :game_id
                    """)
                    
                    # Prepare parameters
                    params = {
                        'game_id': pred_row['game_id'],
                        'away_actual_pts': convert_numpy_types(away_actual_points),
                        'home_actual_pts': convert_numpy_types(home_actual_points),
                        'actual_winner': actual_winner,
                        'away_actual_yds': convert_numpy_types(away_actual_stats.iloc[0]['total_yards']),
                        'home_actual_yds': convert_numpy_types(home_actual_stats.iloc[0]['total_yards']),
                        'away_actual_pass': convert_numpy_types(away_actual_stats.iloc[0]['passing_yards']),
                        'home_actual_pass': convert_numpy_types(home_actual_stats.iloc[0]['passing_yards']),
                        'away_actual_rush': convert_numpy_types(away_actual_stats.iloc[0]['rushing_yards']),
                        'home_actual_rush': convert_numpy_types(home_actual_stats.iloc[0]['rushing_yards']),
                        'pts_diff_away': convert_numpy_types(away_actual_points - pred_row['away_predicted_points']),
                        'pts_diff_home': convert_numpy_types(home_actual_points - pred_row['home_predicted_points']),
                        'yds_diff_away': convert_numpy_types(away_actual_stats.iloc[0]['total_yards'] - pred_row['away_predicted_total_yards']),
                        'yds_diff_home': convert_numpy_types(home_actual_stats.iloc[0]['total_yards'] - pred_row['home_predicted_total_yards']),
                        'pass_diff_away': convert_numpy_types(away_actual_stats.iloc[0]['passing_yards'] - pred_row['away_predicted_passing_yards']),
                        'pass_diff_home': convert_numpy_types(home_actual_stats.iloc[0]['passing_yards'] - pred_row['home_predicted_passing_yards']),
                        'rush_diff_away': convert_numpy_types(away_actual_stats.iloc[0]['rushing_yards'] - pred_row['away_predicted_rushing_yards']),
                        'rush_diff_home': convert_numpy_types(home_actual_stats.iloc[0]['rushing_yards'] - pred_row['home_predicted_rushing_yards']),
                        'winner_correct': bool(pred_row['predicted_winner'] == actual_winner)
                    }
                    
                    # Convert numpy types
                    params = prepare_db_params(params)
                    conn.execute(update_query, params)
                    updates_count += 1
                
                conn.commit()
                print(f"Updated {updates_count} games from week {previous_week} with actual results")
                return True
                
        except Exception as e:
            print(f"Error updating previous week: {e}")
            return False
    
    def update_week_results(self, week, season=2025):
        """Update the week's results in week_game_results"""
        print(f"Updating results for week {week}...")
        
        try:
            with self.engine.connect() as conn:
                # Get the week's prediction data
                week_query = text("""
                    SELECT * FROM game_predictions 
                    WHERE season = :season AND week = :week
                """)
                
                # Convert parameters to native types
                params = prepare_db_params({"season": season, "week": week})
                week_data = pd.read_sql(week_query, conn, params=params)
                
                if week_data.empty:
                    print(f"No predictions for week {week}")
                    return False
                
                total_games = len(week_data)
                games_with_results = len(week_data.dropna(subset=['away_actual_points']))
                
                if games_with_results > 0:
                    results_data = week_data.dropna(subset=['away_actual_points'])
                    correct_predictions = results_data['winner_prediction_correct'].sum()
                    incorrect_predictions = games_with_results - correct_predictions
                    accuracy = correct_predictions / games_with_results if games_with_results > 0 else 0
                    
                    # Compute average errors
                    avg_points_error = (abs(results_data['points_diff_away']).mean() + abs(results_data['points_diff_home']).mean()) / 2
                    avg_total_yards_error = (abs(results_data['total_yards_diff_away']).mean() + abs(results_data['total_yards_diff_home']).mean()) / 2
                    avg_passing_yards_error = (abs(results_data['passing_yards_diff_away']).mean() + abs(results_data['passing_yards_diff_home']).mean()) / 2
                    avg_rushing_yards_error = (abs(results_data['rushing_yards_diff_away']).mean() + abs(results_data['rushing_yards_diff_home']).mean()) / 2
                    
                    # Confidence analysis
                    high_conf_data = results_data[results_data['confidence'] > 0.7]
                    high_confidence_games = len(high_conf_data)
                    high_confidence_correct = high_conf_data['winner_prediction_correct'].sum() if not high_conf_data.empty else 0
                    high_confidence_accuracy = high_confidence_correct / high_confidence_games if high_confidence_games > 0 else 0
                    
                    # Close games vs blowouts analysis
                    close_games_predicted = len(week_data[week_data['point_differential'] < 7])
                    blowout_games_predicted = len(week_data[week_data['point_differential'] > 14])
                    
                    close_games_actual = len(results_data[abs(results_data['away_actual_points'] - results_data['home_actual_points']) < 7])
                    blowout_games_actual = len(results_data[abs(results_data['away_actual_points'] - results_data['home_actual_points']) > 14])
                else:
                    correct_predictions = incorrect_predictions = 0
                    accuracy = 0
                    avg_points_error = avg_total_yards_error = avg_passing_yards_error = avg_rushing_yards_error = None
                    high_confidence_games = high_confidence_correct = 0
                    high_confidence_accuracy = 0
                    close_games_predicted = blowout_games_predicted = 0
                    close_games_actual = blowout_games_actual = 0
                
                # Insert or update results
                upsert_query = text("""
                    INSERT INTO week_game_results (
                        season, week, total_games, games_with_results,
                        correct_predictions, incorrect_predictions, accuracy,
                        avg_points_error, avg_total_yards_error, 
                        avg_passing_yards_error, avg_rushing_yards_error,
                        high_confidence_games, high_confidence_correct, high_confidence_accuracy,
                        close_games_predicted, close_games_actual,
                        blowout_games_predicted, blowout_games_actual
                    ) VALUES (
                        :season, :week, :total_games, :games_with_results,
                        :correct_predictions, :incorrect_predictions, :accuracy,
                        :avg_points_error, :avg_total_yards_error,
                        :avg_passing_yards_error, :avg_rushing_yards_error,
                        :high_confidence_games, :high_confidence_correct, :high_confidence_accuracy,
                        :close_games_predicted, :close_games_actual,
                        :blowout_games_predicted, :blowout_games_actual
                    )
                    ON CONFLICT (season, week) DO UPDATE SET
                        total_games = EXCLUDED.total_games,
                        games_with_results = EXCLUDED.games_with_results,
                        correct_predictions = EXCLUDED.correct_predictions,
                        incorrect_predictions = EXCLUDED.incorrect_predictions,
                        accuracy = EXCLUDED.accuracy,
                        avg_points_error = EXCLUDED.avg_points_error,
                        avg_total_yards_error = EXCLUDED.avg_total_yards_error,
                        avg_passing_yards_error = EXCLUDED.avg_passing_yards_error,
                        avg_rushing_yards_error = EXCLUDED.avg_rushing_yards_error,
                        high_confidence_games = EXCLUDED.high_confidence_games,
                        high_confidence_correct = EXCLUDED.high_confidence_correct,
                        high_confidence_accuracy = EXCLUDED.high_confidence_accuracy,
                        close_games_predicted = EXCLUDED.close_games_predicted,
                        close_games_actual = EXCLUDED.close_games_actual,
                        blowout_games_predicted = EXCLUDED.blowout_games_predicted,
                        blowout_games_actual = EXCLUDED.blowout_games_actual,
                        analysis_date = CURRENT_TIMESTAMP
                """)
                
                # Prepare parameters with type conversion
                params = {
                    'season': season,
                    'week': week,
                    'total_games': total_games,
                    'games_with_results': games_with_results,
                    'correct_predictions': correct_predictions,
                    'incorrect_predictions': incorrect_predictions,
                    'accuracy': accuracy,
                    'avg_points_error': avg_points_error,
                    'avg_total_yards_error': avg_total_yards_error,
                    'avg_passing_yards_error': avg_passing_yards_error,
                    'avg_rushing_yards_error': avg_rushing_yards_error,
                    'high_confidence_games': high_confidence_games,
                    'high_confidence_correct': high_confidence_correct,
                    'high_confidence_accuracy': high_confidence_accuracy,
                    'close_games_predicted': close_games_predicted,
                    'close_games_actual': close_games_actual,
                    'blowout_games_predicted': blowout_games_predicted,
                    'blowout_games_actual': blowout_games_actual
                }
                
                # Apply numpy type conversion
                params = prepare_db_params(params)
                
                conn.execute(upsert_query, params)
                conn.commit()
                
                print(f"Week {week} results updated")
                return {
                    'total_games': total_games,
                    'games_with_results': games_with_results,
                    'accuracy': accuracy,
                    'correct_predictions': correct_predictions,
                    'high_confidence_accuracy': high_confidence_accuracy
                }
                
        except Exception as e:
            print(f"Error updating week results: {e}")
            return False
    
    def predict_next_week(self):
        """Predict the next week automatically"""
        next_week = self.get_next_prediction_week()
        
        print(f"\nPREDICTIONS WEEK {next_week} - SEASON {self.current_season}")
        print("=" * 60)
        
        # Get next week's games
        week_games = self.dfS[
            (self.dfS['season'] == self.current_season) & 
            (self.dfS['week'] == next_week)
        ]
        
        if week_games.empty:
            print(f"No games found for week {next_week} of {self.current_season}")
            return []
        
        print(f"Found {len(week_games)} games for week {next_week}")
        predictions = []
        
        for _, game in week_games.iterrows():
            prediction = self.predict_dynamic_game(
                game['away_team'], game['home_team'], 
                next_week, self.current_season
            )
            
            if prediction:
                predictions.append(prediction)
                
                print(f"\n{game['away_team']} @ {game['home_team']}")
                print(f"  Prediction: {prediction['away_predictions']['points']:.1f} - {prediction['home_predictions']['points']:.1f}")
                print(f"  Winner: {prediction['predicted_winner'].upper()}")
                print(f"  Confidence: {prediction['confidence']:.2%}")
        
        return predictions
    
    def get_previous_week_results(self):
        """Get and display the previous week's results"""
        if self.max_available_week == 0:
            print("No previous week results available")
            return None
        
        previous_week = self.max_available_week
        
        try:
            with self.engine.connect() as conn:
                results_query = text("""
                    SELECT * FROM week_game_results 
                    WHERE season = :season AND week = :week
                """)
                
                # Convert parameters to native types
                params = prepare_db_params({"season": self.current_season, "week": previous_week})
                results = pd.read_sql(results_query, conn, params=params)
                
                if not results.empty:
                    result = results.iloc[0]
                    print(f"\nRESULTS WEEK {previous_week} - SEASON {self.current_season}")
                    print("=" * 50)
                    print(f"Total games: {result['total_games']}")
                    print(f"Games with results: {result['games_with_results']}")
                    if result['games_with_results'] > 0:
                        print(f"Correct predictions: {result['correct_predictions']}")
                        print(f"Incorrect predictions: {result['incorrect_predictions']}")
                        print(f"Overall accuracy: {result['accuracy']:.1%}")
                        print(f"Average points error: {result['avg_points_error']:.2f}")
                        print(f"High-confidence games: {result['high_confidence_games']}")
                        print(f"High-confidence accuracy: {result['high_confidence_accuracy']:.1%}")
                        print(f"Close games predicted: {result['close_games_predicted']}")
                        print(f"Close games actual: {result['close_games_actual']}")
                    return result
                else:
                    print(f"No processed results for week {previous_week}")
                    return None
                    
        except Exception as e:
            print(f"Error getting results: {e}")
            return None
    
    def run_automatic_system(self):
        """Run the automatic system: predict next week and show prior results"""
        print("STARTING AUTOMATIC NFL 2025 SYSTEM...")
        
        if not self.connect_database():
            return None
        
        # Create tables if they do not exist
        if not self.create_database_tables():
            return None
        
        # Process data and train models
        self.create_advanced_features()
        self.create_defensive_factors()
        self.calculate_2024_final_stats()
        self.create_matchup_data()
        self.train_models()
        
        print(f"\nModel trained successfully:")
        for metric, result in self.training_results.items():
            print(f"  {metric}: {result['model']} (R²: {result['r2']:.3f})")
        
        # Show previous week results (if any)
        if self.max_available_week > 0:
            # Update previous week results
            self.update_week_results(self.max_available_week, self.current_season)
            self.get_previous_week_results()
        
        # Predict the next week
        next_week = self.get_next_prediction_week()
        predictions = self.predict_next_week()

        if predictions:
            # Save new predictions
            self.save_new_predictions_to_database(predictions)

            # Update previous week with actual results
            if self.update_past_weeks_with_results(next_week, self.current_season):
                print("Previous week updated successfully")
                # Recompute previous week metrics
                if next_week > 1:
                    self.update_week_results(next_week - 1, self.current_season)

        
        print(f"\n{'='*60}")
        print(f"AUTOMATIC SYSTEM COMPLETE")
        print(f"Predictions for week {next_week} saved to the database")
        print(f"{'='*60}")
        
        return predictions

def main():
    """Main entry point to run the automatic system"""
    system = NFLDynamic2025System()
    predictions = system.run_automatic_system()
    return system, predictions

if __name__ == "__main__":
    # Run the automatic system
    nfl_system, predictions = main()
