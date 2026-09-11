import nflreadpy as nfl

teams = nfl.load_teams()
players = nfl.load_players()
schedules = nfl.load_schedules()

print(teams.columns)
print(players.columns)
print(schedules.columns)
