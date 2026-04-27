import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_, text

app = Flask(__name__)
app.secret_key = 'full_fan_secret_key'

# Database Configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///local_iptv.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    referred = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_date = db.Column(db.DateTime, nullable=False)
    is_renewal = db.Column(db.Boolean, default=False) # New field

def get_dashboard_stats():
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def calculate_period(start_date):
        payments = Payment.query.filter(Payment.payment_date >= start_date).all()
        monto = sum(p.amount for p in payments)
        clientes = len(set(p.client_id for p in payments))
        nuevos = len([p for p in payments if not p.is_renewal])
        renovaciones = len([p for p in payments if p.is_renewal])
        monto_nuevos = sum(p.amount for p in payments if not p.is_renewal)
        monto_renovaciones = sum(p.amount for p in payments if p.is_renewal)
        return {
            'monto': monto,
            'clientes': clientes,
            'nuevos': nuevos,
            'renovaciones': renovaciones,
            'monto_nuevos': monto_nuevos,
            'monto_renovaciones': monto_renovaciones
        }

    return {
        'hoy': calculate_period(today_start),
        'mes': calculate_period(month_start)
    }

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    
    if user.role == 'admin':
        try:
            stats = get_dashboard_stats()
            recent_clients = Client.query.order_by(Client.created_at.desc()).limit(5).all()
            return render_template('index.html', user=user, stats=stats, recent_clients=recent_clients)
        except Exception as e:
            # Fallback if there's still a DB error
            return f"Error cargando dashboard: {str(e)}"
    else:
        return render_template('index_staff.html', user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password, request.form['password']):
            session['user_id'] = u.id
            session['role'] = u.role
            return redirect(url_for('index'))
        flash('Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register-payment/<int:client_id>', methods=['POST'])
def register_payment(client_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    
    existing_payment = Payment.query.filter_by(client_id=client_id).first()
    is_renewal = True if existing_payment else False
    
    new_payment = Payment(
        client_id=client_id,
        amount=float(request.form['amount']),
        expiry_date=datetime.strptime(request.form['expiry_date'], '%Y-%m-%d'),
        is_renewal=is_renewal
    )
    db.session.add(new_payment)
    db.session.commit()
    flash('Pago registrado con éxito')
    return redirect(url_for('client_detail', id=client_id))

@app.route('/clients')
def list_clients():
    if 'user_id' not in session: return redirect(url_for('login'))
    search = request.args.get('search', '')
    if search:
        clients = Client.query.filter((Client.name.ilike(f'%{search}%')) | (Client.username.ilike(f'%{search}%'))).all()
    else:
        clients = Client.query.limit(50).all()
    return render_template('clients.html', clients=clients)

@app.route('/client/<int:id>')
def client_detail(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    client = Client.query.get_or_404(id)
    payments = Payment.query.filter_by(client_id=id).order_by(Payment.payment_date.desc()).all()
    return render_template('client_detail.html', client=client, payments=payments)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # MIGRATION: Add is_renewal column to existing SQLite or Postgres database
        try:
            # For SQLite, ALTER TABLE ADD COLUMN is supported.
            # For PostgreSQL, same syntax works.
            db.session.execute(text('ALTER TABLE payment ADD COLUMN is_renewal BOOLEAN DEFAULT FALSE;'))
            db.session.commit()
        except Exception as e:
            # If it fails, it means the column already exists, so we just rollback and continue.
            db.session.rollback()
            
        # Ensure default users exist
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
            staff = User(username='atencion', password=generate_password_hash('atencion123'), role='atencion')
            db.session.add(admin)
            db.session.add(staff)
            db.session.commit()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
