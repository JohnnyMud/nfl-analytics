import nflreadpy as nfl

teams = nfl.load_teams()
players = nfl.load_players()
schedules = nfl.load_schedules()
player_stats = nfl.load_player_stats()

print(teams.columns)
print(players.columns)
print(schedules.columns)
print(player_stats.columns)
