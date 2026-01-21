from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False) # Acts as Email/Login ID
    email = db.Column(db.String(150), unique=True, nullable=True)     # Explicit Email storage
    password = db.Column(db.String(255), nullable=False) 
    is_admin = db.Column(db.Boolean, default=False)
    
    # Access Control
    is_blocked = db.Column(db.Boolean, default=False) # New: Revoke Access
    
    # Subscription Management
    subscription_end = db.Column(db.DateTime, nullable=True)
    is_trial = db.Column(db.Boolean, default=False)
    
    # Zerodha Credentials
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
        if self.is_admin: return True
        return self.subscription_end and self.subscription_end > datetime.now()

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    data = db.Column(db.Text, nullable=False) 

class ActiveTrade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Text, nullable=False) 

class TradeHistory(db.Model):
    id = db.Column(db.BigInteger, primary_key=True)
    data = db.Column(db.Text, nullable=False) 

class RiskState(db.Model):
    id = db.Column(db.String(50), primary_key=True) 
    data = db.Column(db.Text, nullable=False) 

class TelegramMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.String(50), nullable=False, index=True)
    message_id = db.Column(db.Integer, nullable=False)
    chat_id = db.Column(db.String(50), nullable=False)
