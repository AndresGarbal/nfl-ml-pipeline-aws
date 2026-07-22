from enum import Enum
from typing import Any, List, TypeVar, Type, Callable, cast


T = TypeVar("T")
EnumT = TypeVar("EnumT", bound=Enum)


def from_str(x: Any) -> str:
    assert isinstance(x, str)
    return x


def to_enum(c: Type[EnumT], x: Any) -> EnumT:
    assert isinstance(x, c)
    return x.value


def from_int(x: Any) -> int:
    assert isinstance(x, int) and not isinstance(x, bool)
    return x


def from_list(f: Callable[[Any], T], x: Any) -> List[T]:
    assert isinstance(x, list)
    return [f(y) for y in x]


def to_class(c: Type[T], x: Any) -> dict:
    assert isinstance(x, c)
    return cast(Any, x).to_dict()


class GameStatus(Enum):
    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In Progress"
    FINAL = "Final"
    FINAL_OT = "Final/OT"  # Overtime final
    POSTPONED = "Postponed"
    CANCELLED = "Cancelled"
    UNKNOWN = "Unknown"  # Fallback for unexpected cases


class GameWeek(Enum):
    WEEK_1 = "Week 1"
    WEEK_2 = "Week 2"
    WEEK_3 = "Week 3"
    WEEK_4 = "Week 4"
    WEEK_5 = "Week 5"
    WEEK_6 = "Week 6"
    WEEK_7 = "Week 7"
    WEEK_8 = "Week 8"
    WEEK_9 = "Week 9"
    WEEK_10 = "Week 10"
    WEEK_11 = "Week 11"
    WEEK_12 = "Week 12"
    WEEK_13 = "Week 13"
    WEEK_14 = "Week 14"
    WEEK_15 = "Week 15"
    WEEK_16 = "Week 16"
    WEEK_17 = "Week 17"
    WEEK_18 = "Week 18"
    WEEK_19 = "Week 19"
    WEEK_20 = "Week 20"
    WEEK_21 = "Week 21"
    WEEK_22 = "Week 22"
    WEEK_23 = "Week 23"


class NeutralSite(Enum):
    FALSE = "False"
    TRUE = "True"


class SeasonType(Enum):
    PRESEASON = "Preseason"
    REGULAR = "Regular Season"
    POSTSEASON = "Postseason"


class Body:
    game_id: str
    season_type: SeasonType
    away: str
    game_date: int
    espn_id: int
    team_id_home: int
    game_status: GameStatus
    game_week: GameWeek
    team_id_away: int
    home: str
    espn_link: str
    cbs_link: str
    game_time: str
    game_time_epoch: str
    season: int
    neutral_site: NeutralSite
    game_status_code: int

    def __init__(self, game_id: str, season_type: SeasonType, away: str, game_date: int, espn_id: int, team_id_home: int, game_status: GameStatus, game_week: GameWeek, team_id_away: int, home: str, espn_link: str, cbs_link: str, game_time: str, game_time_epoch: str, season: int, neutral_site: NeutralSite, game_status_code: int) -> None:
        self.game_id = game_id
        self.season_type = season_type
        self.away = away
        self.game_date = game_date
        self.espn_id = espn_id
        self.team_id_home = team_id_home
        self.game_status = game_status
        self.game_week = game_week
        self.team_id_away = team_id_away
        self.home = home
        self.espn_link = espn_link
        self.cbs_link = cbs_link
        self.game_time = game_time
        self.game_time_epoch = game_time_epoch
        self.season = season
        self.neutral_site = neutral_site
        self.game_status_code = game_status_code

    @staticmethod
    def from_dict(obj: Any) -> 'Body':
        assert isinstance(obj, dict)
        game_id = from_str(obj.get("gameID"))
        season_type = SeasonType(obj.get("seasonType"))
        away = from_str(obj.get("away"))
        game_date = int(from_str(obj.get("gameDate")))
        espn_id = int(from_str(obj.get("espnID")))
        team_id_home = int(from_str(obj.get("teamIDHome")))
        game_status = GameStatus(obj.get("gameStatus"))
        game_week = GameWeek(obj.get("gameWeek"))
        team_id_away = int(from_str(obj.get("teamIDAway")))
        home = from_str(obj.get("home"))
        espn_link = from_str(obj.get("espnLink"))
        cbs_link = from_str(obj.get("cbsLink"))
        game_time = from_str(obj.get("gameTime"))
        game_time_epoch = from_str(obj.get("gameTime_epoch"))
        season = int(from_str(obj.get("season")))
        neutral_site = NeutralSite(obj.get("neutralSite"))
        game_status_code = int(from_str(obj.get("gameStatusCode")))
        return Body(game_id, season_type, away, game_date, espn_id, team_id_home, game_status, game_week, team_id_away, home, espn_link, cbs_link, game_time, game_time_epoch, season, neutral_site, game_status_code)

    def to_dict(self) -> dict:
        result: dict = {}
        result["gameID"] = from_str(self.game_id)
        result["seasonType"] = to_enum(SeasonType, self.season_type)
        result["away"] = from_str(self.away)
        result["gameDate"] = from_str(str(self.game_date))
        result["espnID"] = from_str(str(self.espn_id))
        result["teamIDHome"] = from_str(str(self.team_id_home))
        result["gameStatus"] = to_enum(GameStatus, self.game_status)
        result["gameWeek"] = to_enum(GameWeek, self.game_week)
        result["teamIDAway"] = from_str(str(self.team_id_away))
        result["home"] = from_str(self.home)
        result["espnLink"] = from_str(self.espn_link)
        result["cbsLink"] = from_str(self.cbs_link)
        result["gameTime"] = from_str(self.game_time)
        result["gameTime_epoch"] = from_str(self.game_time_epoch)
        result["season"] = from_str(str(self.season))
        result["neutralSite"] = to_enum(NeutralSite, self.neutral_site)
        result["gameStatusCode"] = from_str(str(self.game_status_code))
        return result


class Schedule:
    status_code: int
    body: List[Body]

    def __init__(self, status_code: int, body: List[Body]) -> None:
        self.status_code = status_code
        self.body = body

    @staticmethod
    def from_dict(obj: Any) -> 'Schedule':
        assert isinstance(obj, dict)
        status_code = from_int(obj.get("statusCode"))
        body = from_list(Body.from_dict, obj.get("body"))
        return Schedule(status_code, body)

    def to_dict(self) -> dict:
        result: dict = {}
        result["statusCode"] = from_int(self.status_code)
        result["body"] = from_list(lambda x: to_class(Body, x), self.body)
        return result


def schedule_from_dict(s: Any) -> Schedule:
    return Schedule.from_dict(s)


def schedule_to_dict(x: Schedule) -> Any:
    return to_class(Schedule, x)