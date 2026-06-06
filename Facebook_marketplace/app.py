from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
import hashlib

app = Flask(__name__)
# Change this secret key string when moving the site live on the internet
app.secret_key = 'production_ready_secure_session_encryption_string_key'
DB_FILE = 'database.db'

# Setup User Access Tracking Configurations
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id, username, email, is_admin=0):
        self.id = id
        self.username = username
        self.email = email
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, is_admin FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return User(row[0], row[1], row[2], row[3])
    return None

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    """Initializes permanent tables for users, listings, and order workflows."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            followers TEXT,
            price REAL NOT NULL,
            description TEXT,
            url TEXT,
            credentials TEXT NOT NULL,
            is_sold INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            account_id INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            reference_code TEXT UNIQUE,
            status TEXT DEFAULT 'Pending Verification',
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        )
    ''')
    
    # Check if we need to seed the default admin account and listings
    cursor.execute('SELECT COUNT(*) FROM users WHERE username = "admin"')
    if cursor.fetchone()[0] == 0:
        # Default Admin Credentials: Username: admin / Password: adminpassword
        cursor.execute('INSERT INTO users (username, email, password_hash, is_admin) VALUES (?, ?, ?, ?)',
                       ('admin', 'admin@market.com', hash_password('adminpassword'), 1))
        
        cursor.executemany('''
            INSERT INTO accounts (title, followers, price, description, url, credentials)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [
            ("Aged Business Account (2015)", "5,000+", 45.00, "High trust score, fully verified history.", "https://facebook.com", "FB_USER: aged2015_biz | PASS: SecurePass123! | 2FA: K7XJ..."),
            ("Verified Developer Account", "350", 25.00, "Pre-approved developer mode access.", "https://facebook.com", "FB_USER: dev_acc_350 | PASS: DevAccess992# | 2FA: PLQZ...")
        ])
    conn.commit()
    conn.close()

@app.route('/')
def home():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Only display accounts that are not marked as sold
    cursor.execute('SELECT id, title, followers, price, description, url FROM accounts WHERE is_sold = 0')
    listings = cursor.fetchall()
    conn.close()
    return render_template('index.html', listings=listings)

# --- IDENTITY CONTROL PORTS ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        if action == 'register':
            try:
                cursor.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                               (username, email, hash_password(password)))
                conn.commit()
                flash('Account created successfully! Please log in.', 'success')
            except sqlite3.IntegrityError:
                flash('Username or Email already exists.', 'danger')
                
        elif action == 'login':
            cursor.execute('SELECT id, username, email, is_admin FROM users WHERE username = ? AND password_hash = ?',
                           (username, hash_password(password)))
            row = cursor.fetchone()
            if row:
                user_obj = User(row[0], row[1], row[2], row[3])
                login_user(user_obj)
                conn.close()
                if user_obj.is_admin:
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password combination.', 'danger')
        conn.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT orders.id as order_id, orders.payment_method, orders.reference_code, orders.status,
               accounts.title, accounts.price, accounts.credentials
        FROM orders 
        JOIN accounts ON orders.account_id = accounts.id
        WHERE orders.user_id = ?
    ''', (current_user.id,))
    user_orders = cursor.fetchall()
    conn.close()
    return render_template('dashboard.html', orders=user_orders)

# --- TRANSACTION SUBMISSION API ---

@app.route('/api/submit-order', methods=['POST'])
@login_required
def submit_order():
    data = request.get_json()
    account_id = data.get('account_id')
    method = data.get('method')
    reference = data.get('reference')
    status = data.get('status', 'Pending Verification')
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO orders (user_id, account_id, payment_method, reference_code, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (current_user.id, account_id, method, reference, status))
        
        # If order is immediately completed (like via PayPal), lock the listing as sold
        if status == 'Completed':
            cursor.execute('UPDATE accounts SET is_sold = 1 WHERE id = ?', (account_id,))
            
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"error": "This reference identifier code has already been submitted."}), 400

# --- SECURE ADMINISTRATIVE PANEL PORTS ---

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return "Unauthorized Access Denied.", 403
        
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Load orders awaiting manual check
    cursor.execute('''
        SELECT orders.id as order_id, orders.payment_method, orders.reference_code, orders.status,
               users.username, accounts.title, accounts.price, orders.account_id
        FROM orders
        JOIN users ON orders.user_id = users.id
        JOIN accounts ON orders.account_id = accounts.id
    ''')
    all_orders = cursor.fetchall()
    conn.close()
    return render_template('admin.html', orders=all_orders)

@app.route('/admin/approve/<int:order_id>/<int:account_id>', methods=['POST'])
@login_required
def admin_approve(order_id, account_id):
    if not current_user.is_admin:
        return "Unauthorized Access Denied.", 403
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Approve order and flag the associated Facebook profile card as sold
    cursor.execute('UPDATE orders SET status = "Completed" WHERE id = ?', (order_id,))
    cursor.execute('UPDATE accounts SET is_sold = 1 WHERE id = ?', (account_id,))
    conn.commit()
    conn.close()
    flash(f"Order #{order_id} has been successfully verified and approved!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/submit-listing', methods=['POST'])
@login_required
def submit_listing():
    if not current_user.is_admin:
        return "Unauthorized Access Denied.", 403
        
    title = request.form.get('title')
    followers = request.form.get('followers')
    price = request.form.get('price')
    description = request.form.get('description')
    account_url = request.form.get('url')
    credentials = request.form.get('credentials')

    if title and price and credentials:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO accounts (title, followers, price, description, url, credentials)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, followers, float(price), description, account_url if account_url else "#", credentials))
        conn.commit()
        conn.close()
        flash("New inventory account added successfully!", "success")
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)

