"""HarvestLink — rule-based farm-to-market prototype.

No authentication is intentionally enabled in this demo. Never deploy with real
personal/financial data before introducing access control and a payment provider.
"""
from __future__ import annotations

import io
import os
import secrets
import sqlite3
import urllib.parse
import urllib.request
import json
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

import qrcode
from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('HARVESTLINK_DB', str(ROOT / 'data' / 'harvestlink.db')))
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

CROP_LIBRARY = {
    'Tomatoes': 90, 'Kale': 60, 'Spinach': 45, 'Maize': 110,
    'Carrots': 75, 'Potatoes': 100, 'Onions': 120, 'Beans': 75,
    'Peppers': 90, 'Cabbage': 90, 'Other': 80,
}
CROP_IMAGES = {
    'Tomatoes': 'tomatoes', 'Spinach': 'greens', 'Kale': 'greens',
    'Maize': 'maize', 'Carrots': 'carrots', 'Potatoes': 'potatoes',
    'Onions': 'onions', 'Beans': 'beans', 'Peppers': 'peppers',
    'Cabbage': 'greens', 'Other': 'greens',
}
weather_cache = {'at': 0, 'key': None, 'data': None}


def db():
    if 'db' not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA busy_timeout=3000')
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def query(sql, args=(), one=False):
    rows = db().execute(sql, args).fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    result = db().execute(sql, args)
    db().commit()
    return result.lastrowid


def today():
    return date.today()


def date_value(raw, fallback=None):
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return fallback or today()


def number(raw, *, minimum=0, maximum=1_000_000):
    val = float(raw)
    if not (minimum < val <= maximum):
        raise ValueError(f'Enter a number greater than {minimum:g}, up to {maximum:g}.')
    return val


def label_date(iso):
    try:
        return date.fromisoformat(str(iso)).strftime('%d %b %Y')
    except ValueError:
        return iso


def relative_days(iso):
    delta = (date_value(iso) - today()).days
    if delta == 0: return 'Today'
    if delta == 1: return 'Tomorrow'
    if delta == -1: return 'Yesterday'
    return f'In {delta} days' if delta > 0 else f'{abs(delta)} days ago'


@app.template_filter('prettydate')
def prettydate(iso):
    return label_date(iso)


@app.template_filter('money')
def money(value):
    return f'{float(value or 0):,.0f}'


@app.template_filter('relative')
def relative(iso):
    return relative_days(iso)


def profile():
    return query('SELECT * FROM farm_profile WHERE id=1', one=True)


@app.context_processor
def inject():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(24)
    return {
        'csrf': session['csrf'], 'today_iso': today().isoformat(),
        'farm': profile(), 'crop_library': CROP_LIBRARY,
        'active_page': request.endpoint or '',
    }


@app.before_request
def csrf_protect():
    if request.method == 'POST':
        expected = session.get('csrf')
        supplied = request.form.get('_csrf')
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            abort(400, 'Please refresh the page and try again.')


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
      PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS farm_profile (
        id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, location TEXT NOT NULL,
        about TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'KES',
        latitude REAL, longitude REAL, whatsapp TEXT, email TEXT, payment_url TEXT
      );
      CREATE TABLE IF NOT EXISTS fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        area_ha REAL NOT NULL, soil_type TEXT NOT NULL DEFAULT 'Loamy', note TEXT DEFAULT ''
      );
      CREATE TABLE IF NOT EXISTS crops (
        id INTEGER PRIMARY KEY AUTOINCREMENT, field_id INTEGER NOT NULL REFERENCES fields(id),
        name TEXT NOT NULL, variety TEXT DEFAULT '', planted_on TEXT NOT NULL,
        days_to_maturity INTEGER NOT NULL, predicted_on TEXT NOT NULL, forecast_note TEXT NOT NULL,
        expected_qty REAL NOT NULL, unit TEXT NOT NULL DEFAULT 'kg',
        price_per_unit REAL NOT NULL, discount_pct INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, equipment_type TEXT NOT NULL,
        next_service TEXT NOT NULL, notes TEXT DEFAULT ''
      );
      CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, crop_id INTEGER REFERENCES crops(id),
        equipment_id INTEGER REFERENCES equipment(id), task TEXT NOT NULL,
        due_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        category TEXT NOT NULL DEFAULT 'General', source TEXT NOT NULL DEFAULT 'manual'
      );
      CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        item TEXT NOT NULL, amount REAL NOT NULL, date TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT NOT NULL,
        quantity REAL NOT NULL, price REAL NOT NULL, buyer TEXT NOT NULL,
        date TEXT NOT NULL, reservation_id INTEGER UNIQUE
      );
      CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
        crop_id INTEGER NOT NULL REFERENCES crops(id), buyer_name TEXT NOT NULL,
        buyer_contact TEXT NOT NULL, quantity REAL NOT NULL, unit_price REAL NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL DEFAULT 'reserved', payment_status TEXT NOT NULL DEFAULT 'pending'
      );
      CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_date,status);
      CREATE INDEX IF NOT EXISTS ix_res_crop ON reservations(crop_id,status);
    ''')
    if not conn.execute('SELECT id FROM farm_profile WHERE id=1').fetchone():
        conn.execute('''INSERT INTO farm_profile
          (id,name,location,about,currency,latitude,longitude,whatsapp,email,payment_url)
          VALUES (1,?,?,?,?,?,?,?,?,?)''',
          ('Mavuno Family Farm', 'Nakuru, Kenya',
           'Seasonal vegetables, grown thoughtfully and shared directly with our community.',
           'KES', -0.3031, 36.0800, '', '', ''))
    if not conn.execute('SELECT id FROM fields LIMIT 1').fetchone():
        seed_demo(conn)
    conn.commit()
    conn.close()


def seed_demo(conn):
    """Illustrative data; user starts with working examples, not an empty shell."""
    for name, size, soil, note in [
        ('North Meadow', 1.8, 'Loamy', 'Vegetable beds near the water tank'),
        ('River Plot', 2.4, 'Sandy loam', 'Well-drained lower terraces'),
        ('The Orchard', 1.2, 'Clay loam', 'Close to the equipment shed'),
    ]:
        conn.execute('INSERT INTO fields(name,area_ha,soil_type,note) VALUES(?,?,?,?)',
                     (name, size, soil, note))
    demo = [
        (1,'Tomatoes','Roma',-72,90,280,'kg',110),
        (2,'Spinach','Baby leaf',-34,45,180,'bunches',55),
        (2,'Maize','Hybrid 614',-86,110,500,'kg',48),
        (3,'Carrots','Nantes',-65,75,240,'kg',85),
        (1,'Kale','Sukuma wiki',-24,60,160,'bunches',45),
    ]
    for field_id,name,variety,days_ago,growth,qty,unit,price in demo:
        planted=today()+timedelta(days=days_ago)
        predicted=planted+timedelta(days=growth)
        cid=conn.execute('''INSERT INTO crops
            (field_id,name,variety,planted_on,days_to_maturity,predicted_on,forecast_note,
            expected_qty,unit,price_per_unit) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (field_id,name,variety,planted.isoformat(),growth,predicted.isoformat(),
             'Calendar-based demonstration estimate · weather not yet applied',qty,unit,price)).lastrowid
        schedule_crop_tasks(conn,cid,name,planted,predicted)
    for eqtype,name,offset,notes in [
        ('Irrigation','Drip irrigation pump',9,'Inspect filters and pressure levels'),
        ('Machinery','Two-wheel tractor',21,'Oil check and belt inspection'),
    ]:
        due=(today()+timedelta(days=offset)).isoformat()
        equipment_id=conn.execute('INSERT INTO equipment(name,equipment_type,next_service,notes) VALUES(?,?,?,?)',
            (name,eqtype,due,notes)).lastrowid
        conn.execute('''INSERT INTO tasks (equipment_id,task,due_date,category,source)
                        VALUES(?,?,?,?,?)''',(equipment_id,f'Service {name}',due,'Equipment','auto'))
    for offset,category,item,amt in [
        (-13,'Seeds','Vegetable seedlings',3400),(-9,'Irrigation','Pump maintenance',2100),
        (-5,'Fertilizer','Organic compost',2800),(-2,'Transport','Local delivery fuel',1550),
    ]:
        conn.execute('INSERT INTO expenses(category,item,amount,date) VALUES(?,?,?,?)',
            (category,item,amt,(today()+timedelta(days=offset)).isoformat()))
    for offset,item,qty,price,buyer in [
        (-8,'Kale',52,45,'Local cooperative'),(-3,'Spinach',36,55,'Saturday market'),
    ]:
        conn.execute('INSERT INTO sales(item,quantity,price,buyer,date) VALUES(?,?,?,?,?)',
            (item,qty,price,buyer,(today()+timedelta(days=offset)).isoformat()))
    for crop_id,name,contact,qty in [(1,'Amina W.','Demo contact',34),(2,'The Corner Shop','Demo contact',42),(3,'Market Collective','Demo contact',35)]:
        conn.execute('INSERT INTO reservations(code,crop_id,buyer_name,buyer_contact,quantity,unit_price) VALUES(?,?,?,?,?,?)',
            (secrets.token_hex(4).upper(),crop_id,name,contact,qty,
             conn.execute('SELECT price_per_unit FROM crops WHERE id=?',(crop_id,)).fetchone()[0]))


def schedule_crop_tasks(conn,crop_id,crop_name,planted,harvest):
    """Simple recurring calendar; cap the generated future queue."""
    items=[]
    earliest=today()-timedelta(days=1)
    for every,first,cat,verb in [
        (7,7,'Watering','Check soil moisture & water'),
        (28,21,'Fertilizing','Feed & fertilize'),
        (21,28,'Crop care','Scout for pests'),
    ]:
        when=planted+timedelta(days=first)
        while when < earliest:
            when += timedelta(days=every)
        for _ in range(3):
            if when < harvest:
                items.append((crop_id,f'{verb} — {crop_name}',when.isoformat(),cat,'auto'))
            when += timedelta(days=every)
    prep=harvest-timedelta(days=7)
    if prep >= earliest:
        items.append((crop_id,f'Prepare {crop_name} harvest',prep.isoformat(),'Harvest','auto'))
    conn.executemany('''INSERT INTO tasks(crop_id,task,due_date,category,source)
                        VALUES(?,?,?,?,?)''',items)


def get_weather():
    p=profile()
    if p['latitude'] is None or p['longitude'] is None:
        return None
    key=(p['latitude'],p['longitude'])
    if weather_cache['key']==key and time.monotonic()-weather_cache['at'] < 3600:
        return weather_cache['data']
    params=urllib.parse.urlencode({
        'latitude':p['latitude'],'longitude':p['longitude'],
        'daily':'temperature_2m_max,precipitation_sum',
        'current':'temperature_2m,weather_code',
        'forecast_days':7,'timezone':'auto',
    })
    try:
        with urllib.request.urlopen('https://api.open-meteo.com/v1/forecast?'+params,timeout=2.5) as response:
            data=json.load(response)
        daily=data.get('daily',{})
        if data.get('current',{}).get('temperature_2m') is None:
            raise ValueError('Current weather not supplied')
        rainfall=sum(float(x or 0) for x in daily.get('precipitation_sum',[]))
        heat=max((float(x) for x in daily.get('temperature_2m_max',[]) if x is not None),default=0)
        result={'temp':data.get('current',{}).get('temperature_2m'),
                'rain_7d':round(rainfall,1),'max_temp_7d':round(heat,1),
                'location':p['location']}
    except (OSError,ValueError,KeyError,TypeError):
        result=None
    weather_cache.update(key=key,at=time.monotonic(),data=result)
    return result


def forecast(planted,growth_days,weather=None):
    initial=planted+timedelta(days=growth_days)
    shift=0
    note=f'Crop calendar: {growth_days} days from planting'
    # Illustrative heuristic, NOT crop-specific agronomic forecasting.
    if weather:
        if weather['rain_7d'] >= 90:
            shift=2
            note+=' · +2d adjustment for heavy forecast rain'
        elif weather['max_temp_7d'] >= 35 and weather['rain_7d'] < 8:
            shift=2
            note+=' · +2d adjustment for hot, dry forecast'
        else:
            note+=' · 7-day local weather checked (no adjustment)'
    else:
        note+=' · live weather unavailable; calendar estimate only'
    return (initial+timedelta(days=shift)).isoformat(),note


def full_crops():
    data=query('''SELECT c.*, f.name AS field_name,
             COALESCE((SELECT SUM(r.quantity) FROM reservations r
             WHERE r.crop_id=c.id AND r.status='reserved'),0) AS reserved_qty
             FROM crops c JOIN fields f ON c.field_id=f.id
             ORDER BY c.predicted_on ASC''')
    crops=[]
    for crop in data:
        c=dict(crop)
        c['available_qty']=max(0,c['expected_qty']-c['reserved_qty'])
        c['reserved_pct']=round(100*c['reserved_qty']/c['expected_qty']) if c['expected_qty'] else 0
        c['effective_price']=round(c['price_per_unit']*(100-c['discount_pct'])/100,2)
        c['days_left']=(date_value(c['predicted_on'])-today()).days
        c['image']=CROP_IMAGES.get(c['name'],'greens')
        c['stage']='Ready now' if c['days_left']<=0 else 'Coming soon'
        crops.append(c)
    return crops


def get_alerts(crops):
    alerts=[]
    for c in crops:
        if c['days_left']<=21 and c['reserved_pct']<35 and c['available_qty']>0:
            alerts.append({'crop':c,'level':'action','title':f'{c["name"]} could use more buyers',
                'detail':f'{c["reserved_pct"]}% reserved · {abs(c["days_left"])} days to estimated harvest' if c['days_left']>=0
                else f'{c["reserved_pct"]}% reserved · harvest date has passed'})
    return alerts


def stats():
    crops=full_crops()
    sales=query('SELECT COALESCE(SUM(quantity*price),0) AS val FROM sales',one=True)['val']
    costs=query('SELECT COALESCE(SUM(amount),0) AS val FROM expenses',one=True)['val']
    reservations=query("SELECT COUNT(*) AS n FROM reservations WHERE status='reserved'",one=True)['n']
    tasks=query("SELECT COUNT(*) AS n FROM tasks WHERE status='pending'",one=True)['n']
    potential=sum(c['expected_qty']*c['effective_price'] for c in crops)
    return {'crops':len(crops),'sales':sales,'costs':costs,'net':sales-costs,
            'reservations':reservations,'tasks':tasks,'potential':potential}


@app.get('/')
def home():
    crops=full_crops()
    return render_template('index.html', crops=crops[:3], stats=stats(), alerts=get_alerts(crops))


@app.get('/dashboard')
def dashboard():
    crops=full_crops()
    upcoming=query("SELECT * FROM tasks WHERE status='pending' ORDER BY due_date LIMIT 6")
    return render_template('dashboard.html',st=stats(),crops=crops,tasks=upcoming,
                           alerts=get_alerts(crops),weather=get_weather())


@app.route('/fields',methods=['GET','POST'])
def fields():
    if request.method=='POST':
        try:
            name=request.form.get('name','').strip()[:80]
            if len(name)<2: raise ValueError('Enter a field name.')
            area=number(request.form.get('area_ha'),maximum=100_000)
            soil=request.form.get('soil_type','Loamy').strip()[:50]
            execute('INSERT INTO fields(name,area_ha,soil_type,note) VALUES(?,?,?,?)',
                    (name,area,soil,request.form.get('note','').strip()[:250]))
            flash('Field added to your farm.','success')
        except (ValueError,TypeError) as exc: flash(str(exc),'error')
        return redirect(url_for('fields'))
    return render_template('fields.html',fields=query('''SELECT f.*,(SELECT COUNT(*) FROM crops c WHERE c.field_id=f.id) AS crop_count
                                           FROM fields f ORDER BY f.id'''),crops=full_crops())


@app.post('/crops/add')
def add_crop():
    try:
        field=int(request.form.get('field_id','0'))
        if not query('SELECT id FROM fields WHERE id=?',(field,),one=True):
            raise ValueError('Select a valid field.')
        name=request.form.get('name','Other').strip()
        if name not in CROP_LIBRARY: raise ValueError('Choose a crop from the list.')
        variety=request.form.get('variety','').strip()[:80]
        planted=date.fromisoformat(request.form.get('planted_on',''))
        if planted>today()+timedelta(days=365) or planted<today()-timedelta(days=730):
            raise ValueError('Planting date is outside the supported demo range.')
        maturity=int(request.form.get('days_to_maturity') or CROP_LIBRARY[name])
        if not 15<=maturity<=540: raise ValueError('Maturity must be 15–540 days.')
        qty=number(request.form.get('expected_qty'))
        price=number(request.form.get('price_per_unit'))
        unit=request.form.get('unit','kg')
        if unit not in ('kg','bunches','crates','pieces'): raise ValueError('Select a unit.')
        predicted,note=forecast(planted,maturity,get_weather())
        conn=db()
        crop_id=conn.execute('''INSERT INTO crops(field_id,name,variety,planted_on,days_to_maturity,predicted_on,
            forecast_note,expected_qty,unit,price_per_unit) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (field,name,variety,planted.isoformat(),maturity,predicted,note,qty,unit,price)).lastrowid
        schedule_crop_tasks(conn,crop_id,name,planted,date_value(predicted))
        conn.commit()
        flash(f'{name} planted! Its public coming-soon listing and reminders are ready.','success')
    except (ValueError,TypeError,OverflowError) as exc:
        flash(str(exc) or 'Please check the crop details.','error')
    return redirect(url_for('fields'))


@app.route('/activities',methods=['GET','POST'])
def activities():
    if request.method=='POST':
        task=request.form.get('task','').strip()[:130]
        due=request.form.get('due_date','')
        if not task or not date_value(due,None) or not valid_date(due):
            flash('Enter a task and a valid date.','error')
        else:
            execute('INSERT INTO tasks(task,due_date,category,source) VALUES(?,?,?,?)',
                    (task,due,request.form.get('category','General')[:45],'manual'))
            flash('Task added.','success')
        return redirect(url_for('activities'))
    tasks=query('''SELECT t.*, c.name AS crop_name FROM tasks t
                   LEFT JOIN crops c ON c.id=t.crop_id
                   ORDER BY CASE t.status WHEN 'pending' THEN 0 ELSE 1 END, t.due_date LIMIT 100''')
    return render_template('activities.html',tasks=tasks)


def valid_date(value):
    try: date.fromisoformat(value); return True
    except (ValueError,TypeError): return False


@app.post('/activities/<int:task_id>/toggle')
def toggle_task(task_id):
    t=query('SELECT id,status FROM tasks WHERE id=?',(task_id,),one=True)
    if not t: abort(404)
    execute('UPDATE tasks SET status=? WHERE id=?',('done' if t['status']=='pending' else 'pending',task_id))
    flash('Task updated.','success')
    return redirect(url_for('activities'))


@app.route('/equipment',methods=['GET','POST'])
def equipment():
    if request.method=='POST':
        name=request.form.get('name','').strip()[:90]
        due=request.form.get('next_service','')
        if not name or not valid_date(due):
            flash('Provide the equipment name and a valid service date.','error')
        else:
            eid=execute('INSERT INTO equipment(name,equipment_type,next_service,notes) VALUES(?,?,?,?)',
                        (name,request.form.get('equipment_type','Other')[:50],due,
                         request.form.get('notes','').strip()[:300]))
            execute('INSERT INTO tasks(equipment_id,task,due_date,category,source) VALUES(?,?,?,?,?)',
                    (eid,f'Service {name}',due,'Equipment','auto'))
            flash('Equipment added with its service reminder.','success')
        return redirect(url_for('equipment'))
    return render_template('equipment.html',equipment=query('SELECT * FROM equipment ORDER BY next_service'))


@app.get('/marketplace')
def marketplace():
    crops=full_crops()
    search=request.args.get('q','').strip().lower()[:80]
    status=request.args.get('status','all')
    if search:
        crops=[c for c in crops if search in (c['name']+' '+c['variety']+' '+c['field_name']).lower()]
    if status in ('ready','soon'):
        crops=[c for c in crops if (c['days_left']<=0) == (status=='ready')]
    return render_template('marketplace.html',crops=crops,search=search,status=status)


@app.route('/marketplace/<int:crop_id>',methods=['GET','POST'])
def listing(crop_id):
    crop=next((c for c in full_crops() if c['id']==crop_id),None)
    if not crop: abort(404)
    if request.method=='POST':
        name=request.form.get('buyer_name','').strip()[:80]
        contact=request.form.get('buyer_contact','').strip()[:100]
        try:
            qty=number(request.form.get('quantity'))
            if not name or len(contact)<5: raise ValueError('Enter your name and a valid contact.')
            # Serialize the availability check and write to prevent overselling.
            conn=db()
            conn.execute('BEGIN IMMEDIATE')
            reserved=conn.execute('SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE crop_id=? AND status=\'reserved\'',(crop_id,)).fetchone()[0]
            if qty>crop['expected_qty']-reserved+0.00001:
                raise ValueError('Requested quantity exceeds current availability.')
            code=secrets.token_hex(5).upper()
            conn.execute('INSERT INTO reservations(code,crop_id,buyer_name,buyer_contact,quantity,unit_price) VALUES(?,?,?,?,?,?)',
                         (code,crop_id,name,contact,qty,crop['effective_price']))
            conn.commit()
            return redirect(url_for('order_page',code=code))
        except (ValueError,TypeError,sqlite3.Error) as exc:
            db().rollback()
            flash(str(exc) or 'Could not reserve this item.','error')
            return redirect(url_for('listing',crop_id=crop_id))
    return render_template('listing.html',crop=crop)


@app.get('/farm')
def public_farm():
    return render_template('profile.html',crops=full_crops(),st=stats())


@app.get('/reservations')
def reservations():
    orders=query('''SELECT r.*,c.name AS crop_name,c.unit,c.predicted_on,
            c.price_per_unit,c.discount_pct
            FROM reservations r JOIN crops c ON r.crop_id=c.id
            ORDER BY r.created_at DESC''')
    return render_template('reservations.html',orders=orders)


@app.post('/reservations/<int:reservation_id>/paid')
def mark_paid(reservation_id):
    conn=db()
    r=conn.execute('''SELECT r.*,c.name,c.price_per_unit,c.discount_pct
        FROM reservations r JOIN crops c ON c.id=r.crop_id WHERE r.id=?''',(reservation_id,)).fetchone()
    if not r: abort(404)
    if r['status']=='reserved' and r['payment_status']=='pending':
        price=r['unit_price']
        conn.execute('UPDATE reservations SET payment_status=\'confirmed\' WHERE id=?',(reservation_id,))
        conn.execute('''INSERT OR IGNORE INTO sales(item,quantity,price,buyer,date,reservation_id)
            VALUES(?,?,?,?,?,?)''',(r['name'],r['quantity'],price,r['buyer_name'],today().isoformat(),reservation_id))
        conn.commit()
        flash('Payment manually confirmed and sale recorded.','success')
    return redirect(url_for('reservations'))


@app.post('/reservations/<int:reservation_id>/cancel')
def cancel_reservation(reservation_id):
    r=query('SELECT * FROM reservations WHERE id=?',(reservation_id,),one=True)
    if not r: abort(404)
    if r['payment_status']=='confirmed':
        flash('Refund or reconcile payment before cancelling this order.','error')
    else:
        execute('UPDATE reservations SET status=\'cancelled\' WHERE id=?',(reservation_id,))
        flash('Reservation cancelled and stock released.','success')
    return redirect(url_for('reservations'))


@app.get('/reservation/<code>')
def order_page(code):
    r=query('''SELECT r.*,c.name AS crop_name,c.unit,c.predicted_on,c.price_per_unit,c.discount_pct
        FROM reservations r JOIN crops c ON c.id=r.crop_id WHERE r.code=?''',(code.upper(),),one=True)
    if not r: abort(404)
    return render_template('checkout.html',order=r)


@app.get('/qr/<code>.png')
def order_qr(code):
    if not query('SELECT id FROM reservations WHERE code=?',(code.upper(),),one=True): abort(404)
    url=url_for('order_page',code=code.upper(),_external=True)
    img=qrcode.make(url,box_size=8,border=3)
    out=io.BytesIO()
    img.save(out,format='PNG')
    out.seek(0)
    return send_file(out,mimetype='image/png',download_name='harvestlink-order.png',max_age=300)


@app.get('/qr-payment/<code>.png')
def payment_qr(code):
    """Optional QR to a merchant-hosted payment page; no payment verification."""
    if not query('SELECT id FROM reservations WHERE code=?',(code.upper(),),one=True):
        abort(404)
    merchant_url=profile()['payment_url']
    if not merchant_url or not merchant_url.startswith('https://'):
        abort(404)
    img=qrcode.make(merchant_url,box_size=8,border=3)
    out=io.BytesIO()
    img.save(out,format='PNG')
    out.seek(0)
    return send_file(out,mimetype='image/png',download_name='external-payment-link.png',max_age=300)


@app.route('/finance',methods=['GET','POST'])
def finance():
    if request.method=='POST':
        kind=request.form.get('kind')
        try:
            entry_date=request.form.get('date','')
            if not valid_date(entry_date): raise ValueError('Select a valid date.')
            if kind=='expense':
                item=request.form.get('item','').strip()[:100]
                if not item: raise ValueError('Enter an expense description.')
                execute('INSERT INTO expenses(category,item,amount,date) VALUES(?,?,?,?)',
                        (request.form.get('category','Other')[:50],item,
                         number(request.form.get('amount')),entry_date))
            elif kind=='sale':
                item=request.form.get('item','').strip()[:100]
                if not item: raise ValueError('Enter what was sold.')
                execute('INSERT INTO sales(item,quantity,price,buyer,date) VALUES(?,?,?,?,?)',
                        (item,number(request.form.get('quantity')),
                         number(request.form.get('price')),request.form.get('buyer','').strip()[:100] or 'Walk-in buyer',entry_date))
            else: raise ValueError('Invalid entry type.')
            flash('Entry saved to your ledger.','success')
        except (ValueError,TypeError) as exc: flash(str(exc),'error')
        return redirect(url_for('finance'))
    return render_template('finance.html',st=stats(),expenses=query('SELECT * FROM expenses ORDER BY date DESC,id DESC LIMIT 60'),
                           sales=query('SELECT * FROM sales ORDER BY date DESC,id DESC LIMIT 60'))


@app.get('/insights')
def insights():
    crops=full_crops()
    return render_template('insights.html',crops=crops,alerts=get_alerts(crops),weather=get_weather(),st=stats())


@app.post('/discount/<int:crop_id>')
def discount(crop_id):
    c=query('SELECT * FROM crops WHERE id=?',(crop_id,),one=True)
    if not c: abort(404)
    amount=request.form.get('discount_pct','10')
    if amount not in ('0','5','10','15','20'):
        flash('Select a supported discount.','error')
    else:
        execute('UPDATE crops SET discount_pct=? WHERE id=?',(int(amount),crop_id))
        flash(f'{c["name"]} marketplace price updated. Share its listing with buyers.','success')
    return redirect(url_for('insights'))


@app.route('/settings',methods=['GET','POST'])
def settings():
    if request.method=='POST':
        try:
            farm_name=request.form.get('name','').strip()[:90]
            location=request.form.get('location','').strip()[:90]
            if not farm_name or not location: raise ValueError('Farm name and location are required.')
            latitude=float(request.form.get('latitude','0'))
            longitude=float(request.form.get('longitude','0'))
            if not -90<=latitude<=90 or not -180<=longitude<=180:
                raise ValueError('Latitude or longitude out of range.')
            currency=request.form.get('currency','KES').strip().upper()[:6]
            if not currency.isalpha(): raise ValueError('Currency must be a short currency code.')
            payment_url=request.form.get('payment_url','').strip()[:350]
            if payment_url and not payment_url.startswith('https://'):
                raise ValueError('Checkout URL must start with https://')
            execute('''UPDATE farm_profile SET name=?,location=?,about=?,currency=?,latitude=?,longitude=?,
                whatsapp=?,email=?,payment_url=? WHERE id=1''',
                (farm_name,location,request.form.get('about','').strip()[:600],currency,
                 latitude,longitude,request.form.get('whatsapp','').strip()[:35],
                 request.form.get('email','').strip()[:150],payment_url))
            weather_cache['at']=0
            flash('Farm profile updated.','success')
        except (ValueError,TypeError) as exc: flash(str(exc),'error')
        return redirect(url_for('settings'))
    return render_template('settings.html')


@app.errorhandler(404)
def not_found(_e):
    return render_template('error.html',code='404',message='We could not find that patch of land.'),404


@app.errorhandler(400)
def bad_request(_e):
    return render_template('error.html',code='400',message='That request could not be completed. Refresh and try again.'),400


# WSGI imports must initialize the database too (e.g. gunicorn app:app).
init_db()

if __name__=='__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG')=='1',port=int(os.environ.get('PORT','5000')))
