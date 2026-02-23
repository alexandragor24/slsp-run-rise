import os
import json
import requests
from datetime import datetime, timedelta
from collections import defaultdict

# ===== CONFIG =====
CLIENT_ID = os.environ.get('STRAVA_CLIENT_ID')
CLIENT_SECRET = os.environ.get('STRAVA_CLIENT_SECRET')
REFRESH_TOKEN = os.environ.get('STRAVA_REFRESH_TOKEN')
CLUB_ID = os.environ.get('STRAVA_CLUB_ID')

# ===== FUNKCIE =====

def get_access_token():
    """Získaj nový access token pomocou refresh tokenu"""
    url = 'https://www.strava.com/oauth/token'
    data = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'refresh_token': REFRESH_TOKEN,
        'grant_type': 'refresh_token'
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()['access_token']

def get_club_activities(access_token, page=1, per_page=200):
    """Získaj aktivity z klubu"""
    url = f'https://www.strava.com/api/v3/clubs/{CLUB_ID}/activities'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'page': page, 'per_page': per_page}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def get_week_start():
    """Získaj pondelok aktuálneho týždňa"""
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    return start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

def load_cumulative_data():
    """Načítaj existujúce kumulatívne dáta"""
    try:
        with open('data_leaderboard.csv', 'r', encoding='utf-8') as f:
            lines = f.readlines()[1:]  # skip header
            data = {}
            for line in lines:
                if line.strip():
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        name = parts[0]
                        km = float(parts[1])
                        mins = int(parts[2])
                        data[name] = {'km': km, 'mins': mins}
            return data
    except FileNotFoundError:
        return {}

def load_weekly_snapshot():
    """Načítaj týždenný snapshot (pre výpočet denného prírastku)"""
    try:
        with open('weekly_snapshot.json', 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_weekly_snapshot(data):
    """Ulož týždenný snapshot"""
    with open('weekly_snapshot.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_leaderboard(data):
    """Ulož rebríček do CSV"""
    sorted_data = sorted(data.items(), key=lambda x: x[1]['km'], reverse=True)
    with open('data_leaderboard.csv', 'w', encoding='utf-8') as f:
        f.write('Meno,Kilometre,Minuty\n')
        for name, stats in sorted_data:
            f.write(f'{name},{stats["km"]:.1f},{stats["mins"]}\n')

def update_stats_json(total_km, num_runners):
    """Aktualizuj data_stats.json"""
    try:
        with open('data_stats.json', 'r', encoding='utf-8') as f:
            stats = json.load(f)
    except FileNotFoundError:
        stats = {}
    
    stats['runners'] = num_runners
    stats['kilometers'] = round(total_km, 1)
    
    with open('data_stats.json', 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

# ===== MAIN =====

def main():
    print("🏃 Starting Strava leaderboard update...")
    
    # 1. Získaj access token
    print("🔐 Getting access token...")
    access_token = get_access_token()
    
    # 2. Získaj aktivity z klubu
    print(f"📊 Fetching club activities (Club ID: {CLUB_ID})...")
    activities = []
    page = 1
    while True:
        batch = get_club_activities(access_token, page=page)
        if not batch:
            break
        activities.extend(batch)
        page += 1
        if len(batch) < 200:  # last page
            break
    
    print(f"✅ Found {len(activities)} activities")
    
    # 3. Filtruj len aktivity z aktuálneho týždňa
    week_start = get_week_start()
    print(f"📅 Week starts: {week_start.strftime('%Y-%m-%d')}")
    
    # DEBUG: Zobraz prvých 5 aktivít
    print("🔍 Sample activity dates:")
    for i, activity in enumerate(activities[:5]):
        date_str = activity.get('start_date_local') or activity.get('start_date', 'N/A')
        athlete = activity.get('athlete', {})
        name = f"{athlete.get('firstname', '?')} {athlete.get('lastname', '')}"
        print(f"  {i+1}. {date_str} - {name}")
    
    weekly_stats = defaultdict(lambda: {'km': 0, 'mins': 0})
    
    for activity in activities:
        # Získaj dátum aktivity
        activity_date_str = activity.get('start_date_local') or activity.get('start_date')
        if not activity_date_str:
            continue
        
        # Parse datetime (odstráň 'Z' alebo časové pásmo)
        try:
            activity_date = datetime.fromisoformat(activity_date_str.replace('Z', '').replace('+00:00', ''))
        except:
            continue
        
        if activity_date >= week_start:
            athlete = activity.get('athlete', {})
            firstname = athlete.get('firstname', 'Unknown')
            lastname = athlete.get('lastname', '')
            name = f"{firstname} {lastname}".strip()
            
            distance_km = activity.get('distance', 0) / 1000  # meters to km
            moving_time_mins = activity.get('moving_time', 0) // 60  # seconds to minutes
            
            weekly_stats[name]['km'] += distance_km
            weekly_stats[name]['mins'] += moving_time_mins
    
    print(f"👥 Active runners this week: {len(weekly_stats)}")
    
    # 4. Načítaj predchádzajúce dáta
    cumulative_data = load_cumulative_data()
    last_weekly_snapshot = load_weekly_snapshot()
    
    # 5. Vypočítaj denný prírastok
    daily_increment = {}
    for name, current_week in weekly_stats.items():
        last_week = last_weekly_snapshot.get(name, {'km': 0, 'mins': 0})
        daily_increment[name] = {
            'km': current_week['km'] - last_week['km'],
            'mins': current_week['mins'] - last_week['mins']
        }
    
    # 6. Aktualizuj kumulatívne dáta
    for name, increment in daily_increment.items():
        if name not in cumulative_data:
            cumulative_data[name] = {'km': 0, 'mins': 0}
        cumulative_data[name]['km'] += increment['km']
        cumulative_data[name]['mins'] += increment['mins']
    
    # 7. Ulož výsledky
    save_leaderboard(cumulative_data)
    save_weekly_snapshot(dict(weekly_stats))
    
    # 8. Aktualizuj stats.json
    total_km = sum(stats['km'] for stats in cumulative_data.values())
    update_stats_json(total_km, len(cumulative_data))
    
    print(f"✅ Leaderboard updated! Total: {total_km:.1f} km")
    print("🎉 Done!")

if __name__ == '__main__':
    main()
