import os
import uuid
import secrets
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, abort, send_from_directory)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)

# ============================================================
#  CONFIG
# ============================================================
app.secret_key = os.environ.get('SECRET_KEY') or 'carefor_now_fallback_key_change_in_production'
if not os.environ.get('SECRET_KEY'):
    print("WARNING: SECRET_KEY not set in .env — using fallback key.")

db_url = os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg://')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size':     5,
    'max_overflow':  10,
    'pool_timeout':  30,
    'pool_recycle':  1800,
    'pool_pre_ping': True,
}

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

UPLOAD_FOLDER      = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db = SQLAlchemy(app)

VALID_CASE_STATUSES = {
    'submitted', 'verified', 'partially_funded',
    'fully_funded', 'funded', 'closed', 'rejected'
}


# ============================================================
#  MODELS
# ============================================================

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.String(50),  primary_key=True)
    email         = db.Column(db.String(200), unique=True, nullable=False)
    name          = db.Column(db.String(200))
    phone         = db.Column(db.String(20))
    user_type     = db.Column(db.String(50),  nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    location      = db.Column(db.String(200), nullable=True)
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)

    cases        = db.relationship('Case',        backref='user', lazy=True)
    applications = db.relationship('Application', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False  # no password set — force re-registration
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id, 'email': self.email,
            'name': self.name, 'user_type': self.user_type,
            'location': self.location or '',
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else ''
        }


class Case(db.Model):
    __tablename__ = 'cases'
    id                = db.Column(db.String(50),  primary_key=True)
    user_id           = db.Column(db.String(50),  db.ForeignKey('users.id'), nullable=False)
    patient_name      = db.Column(db.String(200), nullable=False)
    age               = db.Column(db.Integer)
    gender            = db.Column(db.String(20))
    illness_type      = db.Column(db.String(100))
    hospital_name     = db.Column(db.String(200))
    hospital_location = db.Column(db.String(200))
    estimated_cost    = db.Column(db.Integer, default=0)
    amount_received   = db.Column(db.Integer, default=0)
    urgency           = db.Column(db.Integer, default=3)
    description       = db.Column(db.Text)
    status            = db.Column(db.String(50), default='submitted')
    verified_by       = db.Column(db.String(50), nullable=True)
    credibility_score = db.Column(db.Integer, default=0)
    created_at        = db.Column(db.DateTime,   default=datetime.utcnow)

    applications = db.relationship('Application',  backref='case', lazy=True)
    documents    = db.relationship('CaseDocument', backref='case', lazy=True)

    @property
    def amount_remaining(self):
        return max(0, (self.estimated_cost or 0) - (self.amount_received or 0))

    @property
    def is_verified(self):
        return self.verified_by is not None

    @property
    def display_status(self):
        s = self.status
        if s == 'submitted':        return 'Pending'
        if s == 'verified':         return 'Verified'
        if s == 'partially_funded': return 'Partially Funded'
        if s == 'fully_funded':     return 'Fully Funded'
        if s == 'funded':           return 'Fully Funded'
        if s == 'closed':           return 'Closed'
        if s == 'rejected':         return 'Rejected'
        return s.replace('_', ' ').title()

    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id,
            'patient_name': self.patient_name, 'age': self.age,
            'gender': self.gender, 'illness_type': self.illness_type,
            'hospital_name': self.hospital_name,
            'hospital_location': self.hospital_location,
            'estimated_cost': self.estimated_cost,
            'amount_received': self.amount_received or 0,
            'amount_remaining': self.amount_remaining,
            'urgency': self.urgency, 'description': self.description,
            'status': self.status, 'is_verified': self.is_verified,
            'credibility_score': self.credibility_score or 0,
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else ''
        }


class CaseDocument(db.Model):
    __tablename__ = 'case_documents'
    id             = db.Column(db.String(50),  primary_key=True)
    case_id        = db.Column(db.String(50),  db.ForeignKey('cases.id'), nullable=False)
    user_id        = db.Column(db.String(50),  db.ForeignKey('users.id'), nullable=False)
    doc_type       = db.Column(db.String(100), nullable=False)
    file_path      = db.Column(db.String(500), nullable=False)
    original_name  = db.Column(db.String(300))
    is_verified    = db.Column(db.Boolean, default=False)
    rejection_note = db.Column(db.Text, nullable=True)
    uploaded_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'doc_type': self.doc_type,
            'file_path': self.file_path, 'original_name': self.original_name,
            'is_verified': self.is_verified or False,
            'rejection_note': self.rejection_note or '',
            'uploaded_at': self.uploaded_at.strftime('%d %b %Y') if self.uploaded_at else ''
        }


class Application(db.Model):
    __tablename__ = 'applications'
    id         = db.Column(db.String(50), primary_key=True)
    case_id    = db.Column(db.String(50), db.ForeignKey('cases.id'),  nullable=False)
    user_id    = db.Column(db.String(50), db.ForeignKey('users.id'),  nullable=False)
    org_id     = db.Column(db.String(50), nullable=False)
    org_name   = db.Column(db.String(200))
    status     = db.Column(db.String(50), default='submitted')
    note       = db.Column(db.Text)
    created_at = db.Column(db.DateTime,  default=datetime.utcnow)
    updated_at = db.Column(db.DateTime,  default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id, 'case_id': self.case_id,
            'org_id': self.org_id, 'org_name': self.org_name,
            'status': self.status, 'note': self.note,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else ''
        }


class FunderProfile(db.Model):
    __tablename__ = 'funder_profiles'
    id                = db.Column(db.String(50),  primary_key=True)
    user_id           = db.Column(db.String(50),  db.ForeignKey('users.id'), nullable=False, unique=True)
    organization_name = db.Column(db.String(200), nullable=False)
    location          = db.Column(db.String(200))
    latitude          = db.Column(db.String(30),  nullable=True)
    longitude         = db.Column(db.String(30),  nullable=True)
    total_funds       = db.Column(db.BigInteger, default=0)
    remaining_funds   = db.Column(db.BigInteger, default=0)
    is_verified       = db.Column(db.Boolean, default=False, nullable=False)
    verification_doc  = db.Column(db.String(500), nullable=True)
    created_at        = db.Column(db.DateTime,   default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)

    allocations = db.relationship('FundAllocation', backref='funder_profile', lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id,
            'organization_name': self.organization_name,
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'total_funds': self.total_funds,
            'remaining_funds': self.remaining_funds,
            'is_verified': self.is_verified,
        }


class FundAllocation(db.Model):
    __tablename__ = 'fund_allocations'
    id                = db.Column(db.String(50), primary_key=True)
    funder_profile_id = db.Column(db.String(50), db.ForeignKey('funder_profiles.id'), nullable=False)
    case_id           = db.Column(db.String(50), db.ForeignKey('cases.id'), nullable=False)
    application_id    = db.Column(db.String(50), db.ForeignKey('applications.id'), nullable=True)
    amount            = db.Column(db.BigInteger, nullable=False)
    note              = db.Column(db.Text)
    allocated_at      = db.Column(db.DateTime,   default=datetime.utcnow)

    case = db.relationship('Case', backref='allocations', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'funder_profile_id': self.funder_profile_id,
            'case_id': self.case_id,
            'application_id': self.application_id,
            'amount': self.amount, 'note': self.note,
            'allocated_at': self.allocated_at.strftime('%d %b %Y, %I:%M %p') if self.allocated_at else '',
        }


# ============================================================
#  CONSTANTS & HELPERS
# ============================================================

ILLNESS_TYPES = [
    "Cancer", "Heart Disease", "Emergency Surgery", "Accident/Trauma",
    "Kidney Disease", "Diabetes", "Critical Illness", "Burn Injury",
    "Neurological Disorder", "Respiratory Issues"
]

FIXED_DOC_TYPES = [
    {'key': 'aadhaar',     'label': 'Aadhaar Card',      'required': True},
    {'key': 'income_cert', 'label': 'Income Certificate', 'required': False},
    {'key': 'ration_card', 'label': 'Ration Card',        'required': False},
    {'key': 'ews_cert',    'label': 'EWS Certificate',    'required': False},
]

DOC_POINTS = {
    'aadhaar':     40,
    'income_cert': 25,
    'ration_card': 20,
    'ews_cert':    15,
    'additional':   5,
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file_obj, user_id, doc_type):
    user_dir = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_dir, exist_ok=True)
    ext      = file_obj.filename.rsplit('.', 1)[1].lower() if '.' in file_obj.filename else 'bin'
    filename = secure_filename(f"{doc_type}_{uuid.uuid4().hex[:8]}.{ext}")
    file_obj.save(os.path.join(user_dir, filename))
    return f"{user_id}/{filename}"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _update_case_funding_status(case):
    if case.status in ('closed', 'rejected'):
        return
    received = case.amount_received or 0
    required = case.estimated_cost or 0
    if received >= required > 0:
        case.status = 'fully_funded'
    elif received > 0:
        case.status = 'partially_funded'
    # Never downgrade — only upgrade status


def _recalculate_credibility(case_id):
    """Recompute credibility score from verified documents. Cap at 100."""
    docs  = CaseDocument.query.filter_by(case_id=case_id).all()
    score = sum(DOC_POINTS.get(d.doc_type, 5) for d in docs if d.is_verified)
    case  = Case.query.get(case_id)
    if case:
        case.credibility_score = min(score, 100)
        db.session.commit()
    return min(score, 100)


def _sort_funders(funders, case_location):
    """Sort by (1) location match, (2) remaining funds descending."""
    if not case_location:
        return sorted(funders, key=lambda f: -(f.remaining_funds or 0))
    loc_lower = case_location.strip().lower()

    def sort_key(f):
        loc_rank = 2
        if f.location:
            fl = f.location.strip().lower()
            if fl == loc_lower:
                loc_rank = 0
            elif loc_lower in fl or fl in loc_lower:
                loc_rank = 1
        return (loc_rank, -(f.remaining_funds or 0))

    return sorted(funders, key=sort_key)


# ============================================================
#  AUTH DECORATORS
# ============================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('user_type') not in roles:
                return render_template('unauthorized.html'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ============================================================
#  ERROR HANDLERS
# ============================================================

@app.errorhandler(413)
def file_too_large(e):
    return jsonify({'success': False, 'message': 'File too large. Maximum upload size is 10 MB.'}), 413

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ============================================================
#  PROTECTED FILE SERVING
# ============================================================

@app.route('/doc/<path:filepath>')
@login_required
def serve_document(filepath):
    # Strip any leading prefix variants
    for prefix in ('uploads/', 'static/uploads/'):
        if filepath.startswith(prefix):
            filepath = filepath[len(prefix):]

    # Try root-level uploads/ first, then static/uploads/ as fallback
    root_upload   = app.config['UPLOAD_FOLDER']
    static_upload = os.path.join(os.path.dirname(__file__), 'static', 'uploads')

    user_type = session.get('user_type')
    if user_type == 'family':
        owner_id = filepath.split('/')[0]
        if owner_id != session['user_id']:
            doc = CaseDocument.query.filter(
                CaseDocument.user_id == session['user_id'],
                CaseDocument.file_path.in_([filepath, f'uploads/{filepath}', f'static/uploads/{filepath}'])
            ).first()
            if not doc:
                abort(403)

    directory = os.path.dirname(filepath)
    filename  = os.path.basename(filepath)

    for base in (root_upload, static_upload):
        full_dir = os.path.join(base, directory)
        if os.path.isfile(os.path.join(full_dir, filename)):
            return send_from_directory(full_dir, filename)

    abort(404)

# ============================================================
#  PUBLIC ROUTES
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data     = request.get_json()
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password are required.'})

        try:
            row = db.session.execute(
                text("SELECT id, email, name, user_type, password_hash FROM users WHERE email = :e"),
                {'e': email}
            ).fetchone()
        except Exception as e:
            return jsonify({'success': False, 'message': f'Database error: {str(e)}'})

        if not row:
            return jsonify({'success': False, 'message': 'No account found with this email. Please register first.'})

        user_id, user_email, user_name, user_type, pw_hash = row

        if not pw_hash:
            return jsonify({'success': False, 'message': 'Account has no password. Please register again with the same email — it will fix your account automatically.'})

        if not check_password_hash(pw_hash, password):
            return jsonify({'success': False, 'message': 'Incorrect password.'})

        session['user_id']   = user_id
        session['email']     = user_email
        session['user_type'] = user_type
        session['name']      = user_name or user_email

        redirects = {
            'family':   '/dashboard',
            'hospital': '/hospital-dashboard',
            'funder':   '/funder-dashboard',
            'admin':    '/admin-dashboard'
        }
        return jsonify({'success': True, 'redirect': redirects.get(user_type, '/dashboard')})
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data      = request.get_json()
        email     = data.get('email', '').strip().lower()
        name      = data.get('name', '').strip()
        phone     = data.get('phone', '').strip()
        password  = data.get('password', '')
        user_type = data.get('user_type', 'family')

        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password are required.'})
        if len(password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'})

        existing = User.query.filter_by(email=email).first()
        if existing:
            if not existing.password_hash:
                # Fix broken account — set password and log them in
                existing.set_password(password)
                existing.name  = name or existing.name
                existing.phone = phone or existing.phone
                db.session.commit()
                session['user_id']   = existing.id
                session['email']     = existing.email
                session['user_type'] = existing.user_type
                session['name']      = existing.name or existing.email
                redirects = {
                    'family':   '/dashboard',
                    'hospital': '/hospital-dashboard',
                    'funder':   '/funder-dashboard',
                    'admin':    '/admin-dashboard'
                }
                return jsonify({'success': True, 'redirect': redirects.get(existing.user_type, '/dashboard')})
            return jsonify({'success': False, 'message': 'Email already registered. Please log in.'})

        user_id = f"user_{uuid.uuid4().hex[:8]}"
        pw_hash = generate_password_hash(password)

        try:
            db.session.execute(
                text("""INSERT INTO users (id, email, name, phone, user_type, password_hash, created_at)
                         VALUES (:id, :email, :name, :phone, :user_type, :pw_hash, NOW())"""),
                {'id': user_id, 'email': email, 'name': name,
                 'phone': phone, 'user_type': user_type, 'pw_hash': pw_hash}
            )
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'Registration failed: {str(e)}'})

        session['user_id']   = user_id
        session['email']     = email
        session['user_type'] = user_type
        session['name']      = name

        redirects = {
            'family':   '/dashboard',
            'hospital': '/hospital-dashboard',
            'funder':   '/funder-dashboard',
            'admin':    '/admin-dashboard'
        }
        return jsonify({'success': True, 'redirect': redirects.get(user_type, '/dashboard')})
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ============================================================
#  FAMILY ROUTES
# ============================================================

@app.route('/dashboard')
@role_required('family')
def dashboard():
    user       = User.query.get(session['user_id'])
    user_cases = Case.query.filter_by(user_id=session['user_id'])\
                           .order_by(Case.created_at.desc()).all()
    return render_template('dashboard.html', user=user, cases=user_cases)


@app.route('/emergency-case', methods=['GET', 'POST'])
@role_required('family')
def emergency_case():
    if request.method == 'POST':
        if request.content_type and 'multipart/form-data' in request.content_type:
            form    = request.form
            user_id = session['user_id']

            aadhaar_file = request.files.get('doc_aadhaar')
            if not aadhaar_file or not aadhaar_file.filename:
                return jsonify({'success': False, 'message': 'Aadhaar card is required.'})
            if not allowed_file(aadhaar_file.filename):
                return jsonify({'success': False, 'message': 'Aadhaar: only PDF, JPG, PNG allowed.'})

            case_id = f"case_{uuid.uuid4().hex[:8]}"
            case = Case(
                id=case_id, user_id=user_id,
                patient_name=form.get('patient_name', '').strip(),
                age=_safe_int(form.get('age'), 0),
                gender=form.get('gender', ''),
                illness_type=form.get('illness_type', ''),
                hospital_name=form.get('hospital_name', '').strip(),
                hospital_location=form.get('hospital_location', '').strip(),
                estimated_cost=_safe_int(form.get('estimated_cost'), 0),
                urgency=_safe_int(form.get('urgency'), 3),
                description=form.get('description', '').strip(),
                status='submitted', amount_received=0, credibility_score=0
            )
            db.session.add(case)
            db.session.flush()

            fixed_fields = {
                'doc_aadhaar':     'aadhaar',
                'doc_income_cert': 'income_cert',
                'doc_ration_card': 'ration_card',
                'doc_ews_cert':    'ews_cert',
            }
            for field_name, doc_type in fixed_fields.items():
                f = request.files.get(field_name)
                if f and f.filename and allowed_file(f.filename):
                    rel_path = save_uploaded_file(f, user_id, doc_type)
                    db.session.add(CaseDocument(
                        id=f"doc_{uuid.uuid4().hex[:8]}",
                        case_id=case_id, user_id=user_id,
                        doc_type=doc_type, file_path=rel_path,
                        original_name=f.filename
                    ))

            for f in request.files.getlist('doc_extra'):
                if f and f.filename and allowed_file(f.filename):
                    rel_path = save_uploaded_file(f, user_id, 'additional')
                    db.session.add(CaseDocument(
                        id=f"doc_{uuid.uuid4().hex[:8]}",
                        case_id=case_id, user_id=user_id,
                        doc_type='additional', file_path=rel_path,
                        original_name=f.filename
                    ))

            db.session.commit()
            return jsonify({'success': True, 'case_id': case_id})

        else:
            data    = request.get_json()
            case_id = f"case_{uuid.uuid4().hex[:8]}"
            case = Case(
                id=case_id, user_id=session['user_id'],
                patient_name=data.get('patient_name', '').strip(),
                age=_safe_int(data.get('age')),
                gender=data.get('gender', ''),
                illness_type=data.get('illness_type', ''),
                hospital_name=data.get('hospital_name', '').strip(),
                hospital_location=data.get('hospital_location', '').strip(),
                estimated_cost=_safe_int(data.get('estimated_cost')),
                urgency=_safe_int(data.get('urgency'), 3),
                description=data.get('description', '').strip(),
                status='submitted', amount_received=0, credibility_score=0
            )
            db.session.add(case)
            db.session.commit()
            return jsonify({'success': True, 'case_id': case_id})

    return render_template('emergency_case.html',
                           illness_types=ILLNESS_TYPES, doc_types=FIXED_DOC_TYPES)


@app.route('/funding-options/<case_id>')
@role_required('family')
def funding_options(case_id):
    case = Case.query.get(case_id)
    if not case or case.user_id != session['user_id']:
        return redirect(url_for('dashboard'))

    all_funders = FunderProfile.query.filter_by(is_verified=True).all()

    case_location = case.hospital_location or ''
    if not case_location:
        user = User.query.get(session['user_id'])
        case_location = (user.location or '') if user else ''

    all_funders = _sort_funders(all_funders, case_location)

    existing_applications = Application.query.filter_by(
        case_id=case_id, user_id=session['user_id']
    ).all()
    applied_orgs_status = {a.org_id: a.status for a in existing_applications}

    return render_template('funding_options.html',
                           case=case,
                           funders=all_funders,
                           applied_orgs_status=applied_orgs_status,
                           case_location=case_location)


@app.route('/apply-funding', methods=['POST'])
@role_required('family')
def apply_funding():
    data     = request.get_json()
    case_id  = data.get('case_id')
    org_id   = data.get('org_id')
    org_name = data.get('org_name', '')

    case = Case.query.get(case_id)
    if not case or case.user_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Case not found.'})

    funder_user = User.query.filter_by(id=org_id, user_type='funder').first()
    if not funder_user:
        return jsonify({'success': False, 'message': 'Invalid funding organisation.'})

    funder_profile = FunderProfile.query.filter_by(user_id=org_id).first()
    if not funder_profile or not funder_profile.is_verified:
        return jsonify({'success': False, 'message': 'This organisation is not yet approved.'})

    if case.status == 'closed':
        return jsonify({'success': False, 'message': 'This case is closed.'})
    if case.status in ('fully_funded', 'funded'):
        return jsonify({'success': False, 'message': 'This case is already fully funded.'})

    existing = Application.query.filter_by(
        case_id=case_id, org_id=org_id, user_id=session['user_id']
    ).first()
    if existing:
        if existing.status == 'rejected':
            existing.status     = 'submitted'
            existing.note       = ''
            existing.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify({'success': True, 'application_id': existing.id, 'reapplied': True})
        return jsonify({'success': False, 'message': 'Already applied to this organisation.'})

    app_obj = Application(
        id=f"app_{uuid.uuid4().hex[:8]}",
        case_id=case_id, org_id=org_id, org_name=org_name,
        user_id=session['user_id'], status='submitted'
    )
    db.session.add(app_obj)
    db.session.commit()
    return jsonify({'success': True, 'application_id': app_obj.id})


@app.route('/track-status/<case_id>')
@role_required('family')
def track_status(case_id):
    case = Case.query.get(case_id)
    if not case or case.user_id != session['user_id']:
        return redirect(url_for('dashboard'))

    applications = Application.query.filter_by(case_id=case_id)\
                                    .order_by(Application.created_at.desc()).all()
    documents    = CaseDocument.query.filter_by(case_id=case_id)\
                                     .order_by(CaseDocument.uploaded_at.asc()).all()
    allocations  = FundAllocation.query.filter_by(case_id=case_id)\
                                       .order_by(FundAllocation.allocated_at.desc()).all()

    return render_template('track_status.html',
                           case=case,
                           applications=applications,
                           documents=documents,
                           allocations=allocations)


@app.route('/close-case/<case_id>', methods=['POST'])
@role_required('family')
def close_case(case_id):
    case = Case.query.get(case_id)
    if not case or case.user_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Case not found.'})
    if case.status == 'closed':
        return jsonify({'success': False, 'message': 'Already closed.'})
    case.status = 'closed'
    db.session.commit()
    return jsonify({'success': True, 'message': 'Case closed.'})


@app.route('/nearby-support')
@role_required('family')
def nearby_support():
    db_funders = FunderProfile.query\
        .filter_by(is_verified=True)\
        .order_by(FunderProfile.remaining_funds.desc())\
        .all()
    return render_template('nearby_support.html', db_funders=db_funders)


# ============================================================
#  HOSPITAL ROUTES
# ============================================================

@app.route('/hospital-dashboard')
@role_required('hospital')
def hospital_dashboard():
    user = User.query.get(session['user_id'])
    all_cases = Case.query.filter(
        Case.status.notin_(['closed', 'rejected'])
    ).order_by(Case.urgency.asc(), Case.created_at.asc()).all()

    submitted_cases = [c for c in all_cases if c.status == 'submitted']
    verified_cases  = Case.query.filter_by(verified_by=session['user_id'])\
                                .order_by(Case.created_at.desc()).all()
    return render_template('hospital_dashboard.html',
                           user=user,
                           submitted_cases=submitted_cases,
                           verified_cases=verified_cases,
                           all_cases=all_cases)


@app.route('/hospital/case-documents/<case_id>')
@role_required('hospital')
def hospital_case_documents(case_id):
    case = Case.query.get(case_id)
    if not case:
        return jsonify({'success': False, 'message': 'Case not found.'})
    documents = CaseDocument.query.filter_by(case_id=case_id).all()
    return jsonify({
        'success': True,
        'documents': [d.to_dict() for d in documents],
        'case': {
            'id': case.id,
            'patient_name': case.patient_name,
            'credibility_score': case.credibility_score or 0
        }
    })


@app.route('/hospital/verify-document', methods=['POST'])
@role_required('hospital')
def hospital_verify_document():
    """Hospital verifies or rejects a single document, recomputes case credibility."""
    data   = request.get_json()
    doc_id = data.get('doc_id')
    action = data.get('action')  # 'verify' or 'reject'
    note   = data.get('note', '')

    doc = CaseDocument.query.get(doc_id)
    if not doc:
        return jsonify({'success': False, 'message': 'Document not found.'})

    if action == 'verify':
        doc.is_verified    = True
        doc.rejection_note = None
        msg = 'Document verified.'
    elif action == 'reject':
        doc.is_verified    = False
        doc.rejection_note = note or 'Rejected by hospital.'
        msg = 'Document marked as invalid.'
    else:
        return jsonify({'success': False, 'message': 'Invalid action.'})

    db.session.commit()
    new_score = _recalculate_credibility(doc.case_id)

    return jsonify({
        'success': True,
        'message': msg,
        'is_verified': doc.is_verified,
        'new_score': new_score
    })


@app.route('/hospital/verify-case', methods=['POST'])
@role_required('hospital')
def hospital_verify_case():
    data    = request.get_json()
    case_id = data.get('case_id')
    action  = data.get('action')
    case    = Case.query.get(case_id)
    if not case:
        return jsonify({'success': False, 'message': 'Case not found.'})

    if action == 'verify':
        case.verified_by = session['user_id']
        if case.status == 'submitted':
            case.status = 'verified'
        msg = 'Case verified. Verification badge added.'
    elif action == 'reject':
        case.status      = 'rejected'
        case.verified_by = None
        msg = 'Case marked as invalid.'
    else:
        return jsonify({'success': False, 'message': 'Invalid action.'})

    db.session.commit()
    return jsonify({'success': True, 'message': msg, 'new_status': case.status})


# ============================================================
#  FUNDER ROUTES
# ============================================================

@app.route('/funder-dashboard')
@role_required('funder')
def funder_dashboard():
    user    = User.query.get(session['user_id'])
    profile = FunderProfile.query.filter_by(user_id=session['user_id']).first()

    raw_applications = Application.query.filter(
        Application.org_id == session['user_id'],
        Application.status.in_(['submitted', 'approved'])
    ).order_by(Application.created_at.asc()).all()

    app_case_ids = list({a.case_id for a in raw_applications})
    cases_map = {}
    if app_case_ids:
        for c in Case.query.filter(Case.id.in_(app_case_ids)).all():
            cases_map[c.id] = c

    my_applications = [
        a for a in raw_applications
        if cases_map.get(a.case_id) and
           cases_map[a.case_id].status not in ('fully_funded', 'funded', 'closed', 'rejected')
    ]

    funder_given_map = {}
    if profile:
        for alloc in FundAllocation.query.filter_by(funder_profile_id=profile.id).all():
            funder_given_map[alloc.case_id] = funder_given_map.get(alloc.case_id, 0) + alloc.amount

    allocations = []
    if profile:
        allocations = FundAllocation.query.filter_by(funder_profile_id=profile.id)\
                                         .order_by(FundAllocation.allocated_at.desc()).all()

    # Load docs for credibility scores visible in funder's application view
    case_docs_map = {}
    for case_id in app_case_ids:
        case_docs_map[case_id] = CaseDocument.query.filter_by(case_id=case_id).all()

    return render_template('funder_dashboard.html',
                           user=user, profile=profile,
                           cases_map=cases_map,
                           my_applications=my_applications,
                           funder_given_map=funder_given_map,
                           allocations=allocations,
                           case_docs_map=case_docs_map)


@app.route('/funder/respond', methods=['POST'])
@role_required('funder')
def funder_respond():
    data           = request.get_json()
    application_id = data.get('application_id')
    note           = data.get('note', '')
    action         = data.get('action', 'reject')

    application = Application.query.get(application_id)
    if not application:
        return jsonify({'success': False, 'message': 'Application not found.'})
    if application.org_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorised.'})

    if action == 'reject':
        application.status = 'rejected'
    elif action == 'approve':
        application.status = 'approved'
    else:
        return jsonify({'success': False, 'message': 'Invalid action.'})

    application.note       = note
    application.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'new_status': application.status})

@app.route('/funder/allocate-from-application', methods=['POST'])
@role_required('funder')
def funder_allocate_from_application():
    profile = FunderProfile.query.filter_by(user_id=session['user_id']).first()
    if not profile:
        return jsonify({'success': False, 'message': 'Set up your organization profile first.'})
    if not profile.is_verified:
        return jsonify({'success': False,
                        'message': 'Your organization is pending admin approval.'})

    data           = request.get_json()
    application_id = data.get('application_id')
    amount         = _safe_int(data.get('amount'))
    note           = data.get('note', '')

    application = Application.query.get(application_id)
    if not application:
        return jsonify({'success': False, 'message': 'Application not found.'})
    if application.org_id != session['user_id']:
        return jsonify({'success': False, 'message': 'Unauthorised.'})
    if application.status == 'rejected':
        return jsonify({'success': False, 'message': 'This application was rejected.'})

    if amount <= 0:
        return jsonify({'success': False, 'message': 'Amount must be greater than zero.'})
    if amount > profile.remaining_funds:
        return jsonify({'success': False,
                        'message': f'Insufficient funds. You have ₹{profile.remaining_funds:,} remaining.'})

    case = Case.query.get(application.case_id)
    if not case:
        return jsonify({'success': False, 'message': 'Case not found.'})
    if case.status in ('closed', 'rejected'):
        return jsonify({'success': False, 'message': f'Case is {case.status}.'})
    if case.status in ('fully_funded', 'funded'):
        return jsonify({'success': False, 'message': 'This case is already fully funded.'})

    remaining_needed = case.amount_remaining
    if remaining_needed <= 0:
        return jsonify({'success': False, 'message': 'This case is already fully funded.'})
    if amount > remaining_needed:
        return jsonify({'success': False,
                        'message': f'Amount exceeds remaining need. Max: ₹{remaining_needed:,}.'})

    application.status     = 'approved'
    application.note       = note
    application.updated_at = datetime.utcnow()

    db.session.add(FundAllocation(
        id=f"alloc_{uuid.uuid4().hex[:8]}",
        funder_profile_id=profile.id,
        case_id=case.id, application_id=application.id,
        amount=amount, note=note, allocated_at=datetime.utcnow()
    ))

    case.amount_received = (case.amount_received or 0) + amount
    _update_case_funding_status(case)
    profile.remaining_funds -= amount
    profile.updated_at       = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'₹{amount:,} allocated to {case.patient_name}\'s case.',
        'remaining_funds': profile.remaining_funds,
        'case_status': case.status,
        'amount_received': case.amount_received,
        'amount_remaining': case.amount_remaining
    })


@app.route('/funder/setup-profile', methods=['GET', 'POST'])
@role_required('funder')
def funder_setup_profile():
    """
    Funder fills org name, location (with Google Maps picker), uploads a
    verification document. Profile is created with is_verified=False and
    awaits admin approval before funds can be allocated.
    """
    profile = FunderProfile.query.filter_by(user_id=session['user_id']).first()

    if request.method == 'POST':
        if request.content_type and 'multipart/form-data' in request.content_type:
            org_name  = request.form.get('organization_name', '').strip()
            location  = request.form.get('location', '').strip()
            latitude  = request.form.get('latitude', '').strip()
            longitude = request.form.get('longitude', '').strip()
            ver_file  = request.files.get('verification_doc')
        else:
            data      = request.get_json() or {}
            org_name  = data.get('organization_name', '').strip()
            location  = data.get('location', '').strip()
            latitude  = data.get('latitude', '').strip()
            longitude = data.get('longitude', '').strip()
            ver_file  = None

        if not org_name:
            return jsonify({'success': False, 'message': 'Organization name is required.'})

        ver_doc_path = None
        if ver_file and ver_file.filename:
            if not allowed_file(ver_file.filename):
                return jsonify({'success': False,
                                'message': 'Verification doc: only PDF, JPG, PNG allowed.'})
            ver_doc_path = save_uploaded_file(ver_file, session['user_id'], 'verification')

        if profile:
            profile.organization_name = org_name
            profile.location          = location
            if latitude:
                profile.latitude  = latitude
            if longitude:
                profile.longitude = longitude
            profile.updated_at = datetime.utcnow()
            if ver_doc_path:
                profile.verification_doc = ver_doc_path
        else:
            if not ver_doc_path:
                return jsonify({'success': False,
                                'message': 'A verification document is required for new registrations.'})
            profile = FunderProfile(
                id=f"fp_{uuid.uuid4().hex[:8]}",
                user_id=session['user_id'],
                organization_name=org_name,
                location=location,
                latitude=latitude or None,
                longitude=longitude or None,
                total_funds=0, remaining_funds=0,
                is_verified=False,
                verification_doc=ver_doc_path
            )
            db.session.add(profile)

        db.session.commit()
        msg = 'Profile updated.' if profile.is_verified else \
              'Profile saved. Awaiting admin approval before you can allocate funds.'
        return jsonify({'success': True, 'message': msg})

    return render_template('funder_profile.html', profile=profile)


@app.route('/funder/add-funds', methods=['POST'])
@role_required('funder')
def funder_add_funds():
    profile = FunderProfile.query.filter_by(user_id=session['user_id']).first()
    if not profile:
        return jsonify({'success': False, 'message': 'Set up your organization profile first.'})
    if not profile.is_verified:
        return jsonify({'success': False, 'message': 'Your organization is pending admin approval.'})
    data   = request.get_json()
    amount = _safe_int(data.get('amount'))
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Amount must be greater than zero.'})
    profile.total_funds     += amount
    profile.remaining_funds += amount
    profile.updated_at       = datetime.utcnow()
    db.session.commit()
    return jsonify({
        'success': True, 'message': 'Funds added.',
        'total_funds': profile.total_funds,
        'remaining_funds': profile.remaining_funds
    })


# ============================================================
#  ADMIN ROUTES
# ============================================================

@app.route('/admin-dashboard')
@role_required('admin')
def admin_dashboard():
    user      = User.query.get(session['user_id'])
    all_users = User.query.order_by(User.created_at.desc()).all()
    all_cases = Case.query.order_by(Case.created_at.desc()).all()
    all_apps  = Application.query.order_by(Application.created_at.desc()).all()
    pending_funders = FunderProfile.query.filter_by(is_verified=False)\
                                         .order_by(FunderProfile.created_at.asc()).all()
    stats = {
        'total_users':     len(all_users),
        'total_cases':     len(all_cases),
        'submitted':       sum(1 for c in all_cases if c.status == 'submitted'),
        'verified':        sum(1 for c in all_cases if c.status == 'verified'),
        'funded':          sum(1 for c in all_cases
                               if c.status in ('funded', 'fully_funded', 'partially_funded')),
        'rejected':        sum(1 for c in all_cases if c.status == 'rejected'),
        'total_apps':      len(all_apps),
        'approved_apps':   sum(1 for a in all_apps if a.status == 'approved'),
        'pending_funders': len(pending_funders),
    }
    return render_template('admin_dashboard.html',
                           user=user, all_users=all_users,
                           all_cases=all_cases, all_apps=all_apps,
                           pending_funders=pending_funders, stats=stats)


@app.route('/admin/approve-funder/<profile_id>', methods=['POST'])
@role_required('admin')
def admin_approve_funder(profile_id):
    profile = FunderProfile.query.get(profile_id)
    if not profile:
        return jsonify({'success': False, 'message': 'Funder profile not found.'})
    profile.is_verified = True
    profile.updated_at  = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'message': 'Funder approved.'})


@app.route('/admin/reject-funder/<profile_id>', methods=['POST'])
@role_required('admin')
def admin_reject_funder(profile_id):
    profile = FunderProfile.query.get(profile_id)
    if not profile:
        return jsonify({'success': False, 'message': 'Funder profile not found.'})
    db.session.delete(profile)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Funder registration rejected.'})


@app.route('/admin/delete-case/<case_id>', methods=['POST'])
@role_required('admin')
def admin_delete_case(case_id):
    case = Case.query.get(case_id)
    if case:
        FundAllocation.query.filter_by(case_id=case_id).delete()
        Application.query.filter_by(case_id=case_id).delete()
        CaseDocument.query.filter_by(case_id=case_id).delete()
        db.session.delete(case)
        db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/change-status', methods=['POST'])
@role_required('admin')
def admin_change_status():
    data    = request.get_json()
    case_id = data.get('case_id')
    status  = data.get('status')
    if status not in VALID_CASE_STATUSES:
        return jsonify({'success': False, 'message': f'Invalid status: {status}'}), 400
    case = Case.query.get(case_id)
    if not case:
        return jsonify({'success': False, 'message': 'Case not found.'}), 404
    case.status = status
    db.session.commit()
    return jsonify({'success': True})


# ============================================================
#  API
# ============================================================

@app.route('/api/user')
def api_user():
    if 'user_id' not in session:
        return jsonify({'logged_in': False})
    user = User.query.get(session['user_id'])
    return jsonify({
        'logged_in': True,
        'user': user.to_dict() if user else {},
        'user_type': session.get('user_type')
    })


@app.route('/api/funders')
@login_required
def api_funders():
    funders = FunderProfile.query.filter_by(is_verified=True).all()
    return jsonify([f.to_dict() for f in funders])


# ============================================================
#  DB MIGRATION (run once after deploying new columns)
# ============================================================

@app.route('/admin/run-migrations', methods=['POST'])
@role_required('admin')
def run_migrations():
    """
    Safe additive migration — adds new columns to existing tables.
    Idempotent: IF NOT EXISTS means running twice is safe.
    Call once after deploying this version to an existing database.
    """
    migrations = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS location VARCHAR(200)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256)",
        "ALTER TABLE funder_profiles ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE NOT NULL",
        "ALTER TABLE funder_profiles ADD COLUMN IF NOT EXISTS verification_doc VARCHAR(500)",
        "ALTER TABLE funder_profiles ADD COLUMN IF NOT EXISTS latitude VARCHAR(30)",
        "ALTER TABLE funder_profiles ADD COLUMN IF NOT EXISTS longitude VARCHAR(30)",
        "ALTER TABLE fund_allocations ADD COLUMN IF NOT EXISTS application_id VARCHAR(50) REFERENCES applications(id)",
        "ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE",
        "ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS rejection_note TEXT",
        "ALTER TABLE cases ADD COLUMN IF NOT EXISTS credibility_score INTEGER DEFAULT 0",
    ]
    results = []
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            results.append({'sql': sql, 'status': 'ok'})
        except Exception as e:
            results.append({'sql': sql, 'status': 'error', 'error': str(e)})
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e), 'results': results})
    return jsonify({'success': True, 'results': results})


# ============================================================
#  STARTUP
# ============================================================

@app.route('/debug-user/<email>')
def debug_user(email):
    user = db.session.execute(
        text("SELECT id, email, user_type, password_hash FROM users WHERE email = :e"),
        {'e': email}
    ).fetchone()
    if not user:
        return f"No user found with email: {email}"
    return f"ID: {user[0]} | Email: {user[1]} | Type: {user[2]} | Hash: {repr(user[3])}"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("Database ready.")
    app.run(debug=True, port=5000)
