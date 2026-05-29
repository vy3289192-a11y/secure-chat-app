from flask import Flask, render_template, request, session, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super_secret_premium_cyber_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

online_users = {}

# ================= DATABASE MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    profile_pic = db.Column(db.Text, default='') 

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    receiver_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, nullable=False)
    receiver_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# ================= PAGES ROUTING =================
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html')

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/register')
def register_page():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('register.html')

# ================= AUTH & PROFILE API =================
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    name = data.get('name', '').strip()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not name or not username or not password:
        return jsonify({'error': 'Saari fields bharna zaroori hai!'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Yeh username pehle se kisi ne le liya hai!'}), 400

    hashed_pw = generate_password_hash(password)
    new_user = User(name=name, username=username, password=hashed_pw)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'success': 'Account ban gaya! Ab login kijiye.'})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password, password):
        session['user_id'] = user.id
        session['username'] = user.username
        session['name'] = user.name
        return jsonify({'success': 'Logged in successfully!'})
    return jsonify({'error': 'Galat username ya password!'}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/api/update_profile', methods=['POST'])
def update_profile():
    user_id = session.get('user_id')
    user = User.query.get(user_id)
    if user:
        data = request.json
        if 'name' in data and data['name'].strip():
            user.name = data['name'].strip()
            session['name'] = user.name
        if 'profile_pic' in data:
            user.profile_pic = data['profile_pic']
        db.session.commit()
        return jsonify({'success': 'Profile updated successfully!'})
    return jsonify({'error': 'User not found!'}), 400

# ================= CHAT FUNCTIONS =================
@app.route('/search_user', methods=['POST'])
def search_user():
    username = request.json.get('username', '').strip().lower()
    user = User.query.filter_by(username=username).first()
    if user and user.id != session.get('user_id'):
        return jsonify({'id': user.id, 'username': user.username, 'name': user.name})
    return jsonify({'error': 'User nahi mila!'}), 404

@app.route('/send_request', methods=['POST'])
def send_request():
    receiver_id = request.json.get('receiver_id')
    sender_id = session.get('user_id')
    existing = Friendship.query.filter_by(sender_id=sender_id, receiver_id=receiver_id).first()
    if not existing:
        new_req = Friendship(sender_id=sender_id, receiver_id=receiver_id)
        db.session.add(new_req)
        db.session.commit()
        return jsonify({'success': 'Request bhej di gayi hai!'})
    return jsonify({'error': 'Request pehle se bheji ja chuki hai!'}), 400

@app.route('/get_friends')
def get_friends():
    user_id = session.get('user_id')
    me = User.query.get(user_id)
    friends_data = []
    requests_data = []
    
    pending_reqs = Friendship.query.filter_by(receiver_id=user_id, status='pending').all()
    for req in pending_reqs:
        sender = User.query.get(req.sender_id)
        if sender:
            requests_data.append({'id': req.id, 'username': sender.username, 'name': sender.name, 'pic': sender.profile_pic})

    friendships = Friendship.query.filter(
        ((Friendship.sender_id == user_id) | (Friendship.receiver_id == user_id)) & (Friendship.status == 'accepted')
    ).all()
    
    for f in friendships:
        friend_id = f.receiver_id if f.sender_id == user_id else f.sender_id
        friend = User.query.get(friend_id)
        if friend:
            is_online = friend_id in online_users
            friends_data.append({'id': friend.id, 'username': friend.username, 'name': friend.name, 'pic': friend.profile_pic, 'is_online': is_online})
        
    return jsonify({
        'friends': friends_data, 
        'requests': requests_data, 
        'my_id': user_id, 
        'my_name': session.get('name'),
        'my_username': session.get('username'),
        'my_pic': me.profile_pic
    })

@app.route('/accept_request', methods=['POST'])
def accept_request():
    req_id = request.json.get('request_id')
    req = Friendship.query.get(req_id)
    if req and req.receiver_id == session.get('user_id'):
        req.status = 'accepted'
        db.session.commit()
        return jsonify({'success': 'Dost add ho gaya!'})
    return jsonify({'error': 'Kuch galat hua!'}), 400

@app.route('/get_messages/<int:friend_id>')
def get_messages(friend_id):
    user_id = session.get('user_id')
    
    time_limit = datetime.utcnow() - timedelta(hours=24)
    Message.query.filter(Message.timestamp < time_limit).delete()
    db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id))
    ).order_by(Message.timestamp.asc()).all()
    
    chat_history = [{'sender_id': m.sender_id, 'text': m.text, 'time': m.timestamp.strftime("%H:%M")} for m in messages]
    return jsonify(chat_history)

# ================= WEBSOCKETS =================
def get_room_name(id1, id2):
    return f"room_{min(id1, id2)}_{max(id1, id2)}"

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id:
        online_users[user_id] = request.sid
        emit('user_status_change', {'user_id': user_id, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id in online_users:
        del online_users[user_id]
        emit('user_status_change', {'user_id': user_id, 'status': 'offline'}, broadcast=True)

@socketio.on('join_private')
def on_join_private(data):
    room = get_room_name(session.get('user_id'), data['friend_id'])
    join_room(room)

@socketio.on('typing')
def handle_typing(data):
    friend_id = data['friend_id']
    room = get_room_name(session.get('user_id'), friend_id)
    emit('display_typing', {'sender_id': session.get('user_id')}, room=room, include_self=False)

@socketio.on('private_message')
def handle_private_message(data):
    user_id = session.get('user_id')
    friend_id = data['friend_id']
    text = data['msg']
    
    new_msg = Message(sender_id=user_id, receiver_id=friend_id, text=text)
    db.session.add(new_msg)
    db.session.commit()

    room = get_room_name(user_id, friend_id)
    time_str = datetime.utcnow().strftime("%H:%M")
    
    emit('receive_message', {'sender_id': user_id, 'text': text, 'time': time_str}, room=room)

if __name__ == '__main__':
    socketio.run(app, debug=True)
