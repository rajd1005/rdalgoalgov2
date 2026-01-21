from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False) # Acts as the primary Login ID (Email)
    email = db.Column(db.String(150), unique=True, nullable=True)     # Explicit Email column for notifications
    password = db.Column(db.String(255), nullable=False) 
    is_admin = db.Column(db.Boolean, default=False)   # Super Admin (Full Access)
    is_manager = db.Column(db.Boolean, default=False) # New: Manager (Admin Panel Access Only, No Dashboard)
    
    # Access Control (Revoke Access)
    is_blocked = db.Column(db.Boolean, default=False)
    
    # Subscription Management
    subscription_end = db.Column(db.DateTime, nullable=True)
    is_trial = db.Column(db.Boolean, default=False)
    
    # Security: OTP & Session Tracking
    otp_code = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    last_login_date = db.Column(db.Date, nullable=True) # Used to trigger OTP once per day
    
    # Zerodha Credentials (Stored as JSON)
    zerodha_creds = db.Column(db.Text, nullable=True) 
    
    def set_creds(self, api_key, api_secret, totp, uid, pwd):
        data = {
            "api_key": api_key,
            "api_secret": api_secret,
            "totp": totp,
            "user_id": uid,
            "password": pwd
        }
        self.zerodha_creds = json.dumps(data)
        
    def get_creds(self):
        if not self.zerodha_creds: return None
        return json.loads(self.zerodha_creds)

    @property
    def is_active_sub(self):
        # Admins and Managers are exempt from subscription checks
        if self.is_admin or self.is_manager: return True
        return self.subscription_end and self.subscription_end > datetime.now()

class SystemConfig(db.Model):
    """
    Stores global system configurations like SMTP settings and Email Templates.
    Key-Value pair storage.
    """
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Linked to User ID for Multi-User Isolation
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    data = db.Column(db.Text, nullable=False) 

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Linked to User ID for Multi-User Isolation (Critical Fix)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    data = db.Column(db.Text, nullable=False) 

class TradeHistory(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    # [FIX] Added user_id column for indexed filtering (Solves Critical Bottleneck)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=True)
    data = db.Column(db.Text, nullable=False) 

class RiskState(db.Model):
    id = db.Column(db.String(50), primary_key=True) # Composite ID: "user_id_mode"
    data = db.Column(db.Text, nullable=False) 

class TelegramMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # [NEW] Link message to user for isolation
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True, nullable=True)
    trade_id = db.Column(db.String(50), nullable=False, index=True)
    message_id = db.Column(db.Integer, nullable=False)
    chat_id = db.Column(db.String(50), nullable=False)
