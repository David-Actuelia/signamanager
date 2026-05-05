"""
Actuelia Signature Manager — Outil interne de gestion de signatures email.
Équivalent interne de Boostmymail.

Usage :
    pip install -r requirements.txt
    python app.py

Puis ouvrir http://localhost:5000
"""

import os
import uuid
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory,
)
from markupsafe import Markup
from jinja2 import Template
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

from models import db, Collaborateur, TemplateSignature, Banniere, DeploiementLog
from outlook_sync import OutlookSync

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
# En production, configurez DATABASE_URL dans .env
# Par défaut, la base est créée dans le même dossier que app.py
_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'signatures.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', f'sqlite:///{_db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'banners')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 Mo max

BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000')

# Paramètres entreprise (personnalisables)
ENTREPRISE = {
    'nom': 'Actuelia',
    'site': 'https://www.actuelia.fr',
    'logo': '',  # URL du logo entreprise
}

db.init_app(app)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Initialisation de la base de données
# ---------------------------------------------------------------------------

def init_db():
    """Crée les tables et insère les templates par défaut."""
    db.create_all()

    if TemplateSignature.query.count() == 0:
        templates_dir = os.path.join(os.path.dirname(__file__), 'signature_templates')
        templates_info = [
            ('Classique', 'Signature professionnelle avec photo et séparateur coloré', 'classique.html', True),
            ('Moderne', 'Design épuré avec barre latérale colorée', 'moderne.html', False),
            ('Minimal', 'Signature compacte et sobre, idéale pour les réponses', 'minimal.html', False),
        ]
        for nom, desc, filename, is_default in templates_info:
            filepath = os.path.join(templates_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
            t = TemplateSignature(nom=nom, description=desc, html_template=html, is_default=is_default)
            db.session.add(t)
        db.session.commit()


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def get_active_banniere():
    """Retourne la bannière active du moment."""
    today = date.today()
    banniere = Banniere.query.filter(
        Banniere.actif == True,
        Banniere.date_debut <= today,
        (Banniere.date_fin >= today) | (Banniere.date_fin == None)
    ).order_by(Banniere.ordre.asc()).first()
    return banniere


def render_banniere_html(banniere, base_url=None):
    """Génère le HTML d'une bannière cliquable."""
    if not banniere:
        return ''
    base = base_url or BASE_URL
    image_url = f"{base}/static/uploads/banners/{os.path.basename(banniere.image_path)}"
    tracking_url = f"{base}/clic/{banniere.id}"
    return (
        f'<a href="{tracking_url}" target="_blank" style="text-decoration: none;">'
        f'<img src="{image_url}" alt="{banniere.alt_text or banniere.nom}" '
        f'style="max-width: 100%; height: auto; display: block; border: 0; border-radius: 4px;" />'
        f'</a>'
    )


def generate_signature_html(collaborateur, base_url=None):
    """Génère le HTML final de la signature d'un collaborateur."""
    template_obj = collaborateur.template
    if not template_obj:
        template_obj = TemplateSignature.query.filter_by(is_default=True).first()
    if not template_obj:
        return '<p>Aucun template disponible</p>'

    banniere = get_active_banniere()
    banniere_html = render_banniere_html(banniere, base_url)
    if banniere:
        banniere.nb_affichages += 1
        db.session.commit()

    jinja_template = Template(template_obj.html_template)
    html = jinja_template.render(
        prenom=collaborateur.prenom,
        nom=collaborateur.nom,
        poste=collaborateur.poste,
        email=collaborateur.email,
        telephone=collaborateur.telephone or '',
        mobile=collaborateur.mobile or '',
        photo_url=collaborateur.photo_url or '',
        linkedin_url=collaborateur.linkedin_url or '',
        departement=collaborateur.departement or '',
        entreprise_nom=ENTREPRISE['nom'],
        entreprise_site=ENTREPRISE['site'],
        entreprise_logo=ENTREPRISE['logo'],
        banniere_html=Markup(banniere_html),
    )
    return html


# ---------------------------------------------------------------------------
# Routes — Pages principales
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Dashboard principal."""
    nb_collabs = Collaborateur.query.filter_by(actif=True).count()
    nb_templates = TemplateSignature.query.count()
    nb_bannieres = Banniere.query.filter_by(actif=True).count()

    # Stats bannières
    bannieres = Banniere.query.all()
    total_clics = sum(b.nb_clics for b in bannieres)
    total_affichages = sum(b.nb_affichages for b in bannieres)

    # Derniers déploiements
    derniers_deploiements = DeploiementLog.query.order_by(
        DeploiementLog.created_at.desc()
    ).limit(10).all()

    return render_template('index.html',
        nb_collabs=nb_collabs,
        nb_templates=nb_templates,
        nb_bannieres=nb_bannieres,
        total_clics=total_clics,
        total_affichages=total_affichages,
        derniers_deploiements=derniers_deploiements,
    )


# ---------------------------------------------------------------------------
# Routes — Collaborateurs
# ---------------------------------------------------------------------------

@app.route('/collaborateurs')
def collaborateurs_list():
    """Liste des collaborateurs."""
    departement = request.args.get('departement', '')
    query = Collaborateur.query
    if departement:
        query = query.filter_by(departement=departement)
    collabs = query.order_by(Collaborateur.nom.asc()).all()

    departements = db.session.query(Collaborateur.departement).distinct().filter(
        Collaborateur.departement != None, Collaborateur.departement != ''
    ).all()
    departements = [d[0] for d in departements]

    templates = TemplateSignature.query.all()
    return render_template('collaborateurs.html',
        collaborateurs=collabs,
        departements=departements,
        departement_filtre=departement,
        templates=templates,
    )


@app.route('/collaborateurs/ajouter', methods=['POST'])
def collaborateur_ajouter():
    """Ajoute un nouveau collaborateur."""
    collab = Collaborateur(
        prenom=request.form['prenom'],
        nom=request.form['nom'],
        email=request.form['email'],
        poste=request.form['poste'],
        telephone=request.form.get('telephone', ''),
        mobile=request.form.get('mobile', ''),
        photo_url=request.form.get('photo_url', ''),
        linkedin_url=request.form.get('linkedin_url', ''),
        departement=request.form.get('departement', ''),
        template_id=request.form.get('template_id') or None,
    )
    db.session.add(collab)
    db.session.commit()
    flash(f'{collab.nom_complet} ajouté avec succès.', 'success')
    return redirect(url_for('collaborateurs_list'))


@app.route('/collaborateurs/<int:id>/modifier', methods=['POST'])
def collaborateur_modifier(id):
    """Modifie un collaborateur existant."""
    collab = Collaborateur.query.get_or_404(id)
    collab.prenom = request.form['prenom']
    collab.nom = request.form['nom']
    collab.email = request.form['email']
    collab.poste = request.form['poste']
    collab.telephone = request.form.get('telephone', '')
    collab.mobile = request.form.get('mobile', '')
    collab.photo_url = request.form.get('photo_url', '')
    collab.linkedin_url = request.form.get('linkedin_url', '')
    collab.departement = request.form.get('departement', '')
    collab.template_id = request.form.get('template_id') or None
    db.session.commit()
    flash(f'{collab.nom_complet} mis à jour.', 'success')
    return redirect(url_for('collaborateurs_list'))


@app.route('/collaborateurs/<int:id>/supprimer', methods=['POST'])
def collaborateur_supprimer(id):
    """Supprime un collaborateur."""
    collab = Collaborateur.query.get_or_404(id)
    nom = collab.nom_complet
    db.session.delete(collab)
    db.session.commit()
    flash(f'{nom} supprimé.', 'info')
    return redirect(url_for('collaborateurs_list'))


@app.route('/collaborateurs/import-csv', methods=['POST'])
def collaborateurs_import_csv():
    """Import en masse depuis un fichier CSV."""
    import csv
    import io

    file = request.files.get('csv_file')
    if not file:
        flash('Aucun fichier sélectionné.', 'error')
        return redirect(url_for('collaborateurs_list'))

    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content), delimiter=';')

    count = 0
    for row in reader:
        if not row.get('email'):
            continue
        existing = Collaborateur.query.filter_by(email=row['email']).first()
        if existing:
            continue
        collab = Collaborateur(
            prenom=row.get('prenom', ''),
            nom=row.get('nom', ''),
            email=row['email'],
            poste=row.get('poste', ''),
            telephone=row.get('telephone', ''),
            mobile=row.get('mobile', ''),
            departement=row.get('departement', ''),
            linkedin_url=row.get('linkedin_url', ''),
        )
        db.session.add(collab)
        count += 1

    db.session.commit()
    flash(f'{count} collaborateur(s) importé(s).', 'success')
    return redirect(url_for('collaborateurs_list'))


# ---------------------------------------------------------------------------
# Routes — Signatures
# ---------------------------------------------------------------------------

@app.route('/signatures')
def signatures_list():
    """Prévisualisation des signatures de tous les collaborateurs."""
    collabs = Collaborateur.query.filter_by(actif=True).order_by(Collaborateur.nom.asc()).all()
    templates = TemplateSignature.query.all()
    return render_template('signatures.html', collaborateurs=collabs, templates=templates)


@app.route('/signatures/preview/<int:collab_id>')
def signature_preview(collab_id):
    """Retourne le HTML de prévisualisation d'une signature."""
    collab = Collaborateur.query.get_or_404(collab_id)
    html = generate_signature_html(collab)
    return html


@app.route('/signatures/preview/<int:collab_id>/template/<int:template_id>')
def signature_preview_template(collab_id, template_id):
    """Prévisualisation avec un template spécifique."""
    collab = Collaborateur.query.get_or_404(collab_id)
    original_template = collab.template_id
    collab.template_id = template_id
    collab.template = TemplateSignature.query.get(template_id)
    html = generate_signature_html(collab)
    collab.template_id = original_template
    return html


@app.route('/signatures/html/<int:collab_id>')
def signature_html_raw(collab_id):
    """Retourne le code HTML brut d'une signature (pour copier/coller)."""
    collab = Collaborateur.query.get_or_404(collab_id)
    html = generate_signature_html(collab, base_url=BASE_URL)
    return jsonify({'html': html, 'collaborateur': collab.nom_complet})


@app.route('/signatures/deploy/<int:collab_id>', methods=['POST'])
def signature_deploy_one(collab_id):
    """Déploie la signature d'un collaborateur vers Outlook."""
    collab = Collaborateur.query.get_or_404(collab_id)
    sync = _get_outlook_sync()
    if not sync:
        flash('Microsoft Graph API non configurée. Vérifiez le fichier .env', 'error')
        return redirect(url_for('signatures_list'))

    html = generate_signature_html(collab, base_url=BASE_URL)
    result = sync.deploy_signature(collab.email, html)

    log = DeploiementLog(
        collaborateur_id=collab.id,
        statut='succes' if result['success'] else 'erreur',
        message=result['message'],
    )
    db.session.add(log)
    db.session.commit()

    if result['success']:
        flash(f'Signature déployée pour {collab.nom_complet}', 'success')
    else:
        flash(f'Erreur : {result["message"]}', 'error')

    return redirect(url_for('signatures_list'))


@app.route('/signatures/deploy-all', methods=['POST'])
def signature_deploy_all():
    """Déploie les signatures de tous les collaborateurs actifs."""
    sync = _get_outlook_sync()
    if not sync:
        flash('Microsoft Graph API non configurée.', 'error')
        return redirect(url_for('signatures_list'))

    collabs = Collaborateur.query.filter_by(actif=True).all()
    success = 0
    errors = 0

    for collab in collabs:
        html = generate_signature_html(collab, base_url=BASE_URL)
        result = sync.deploy_signature(collab.email, html)
        log = DeploiementLog(
            collaborateur_id=collab.id,
            statut='succes' if result['success'] else 'erreur',
            message=result['message'],
        )
        db.session.add(log)
        if result['success']:
            success += 1
        else:
            errors += 1

    db.session.commit()
    flash(f'Déploiement terminé : {success} succès, {errors} erreur(s).', 'success' if errors == 0 else 'warning')
    return redirect(url_for('signatures_list'))


def _get_outlook_sync():
    """Crée une instance OutlookSync si la config est présente."""
    cid = os.getenv('MS_CLIENT_ID')
    secret = os.getenv('MS_CLIENT_SECRET')
    tenant = os.getenv('MS_TENANT_ID')
    if cid and secret and tenant:
        return OutlookSync(cid, secret, tenant)
    return None


# ---------------------------------------------------------------------------
# Routes — Bannières
# ---------------------------------------------------------------------------

@app.route('/bannieres')
def bannieres_list():
    """Gestion des bannières promotionnelles."""
    bannieres = Banniere.query.order_by(Banniere.ordre.asc(), Banniere.created_at.desc()).all()
    return render_template('bannieres.html', bannieres=bannieres)


@app.route('/bannieres/ajouter', methods=['POST'])
def banniere_ajouter():
    """Ajoute une nouvelle bannière."""
    file = request.files.get('image')
    if not file or not allowed_file(file.filename):
        flash('Image invalide. Formats acceptés : PNG, JPG, GIF, WebP', 'error')
        return redirect(url_for('bannieres_list'))

    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(filepath)

    date_fin = request.form.get('date_fin')
    banniere = Banniere(
        nom=request.form['nom'],
        image_path=filepath,
        lien_url=request.form['lien_url'],
        alt_text=request.form.get('alt_text', ''),
        date_debut=datetime.strptime(request.form['date_debut'], '%Y-%m-%d').date(),
        date_fin=datetime.strptime(date_fin, '%Y-%m-%d').date() if date_fin else None,
        actif=True,
        ordre=int(request.form.get('ordre', 0)),
    )
    db.session.add(banniere)
    db.session.commit()
    flash(f'Bannière "{banniere.nom}" ajoutée.', 'success')
    return redirect(url_for('bannieres_list'))


@app.route('/bannieres/<int:id>/toggle', methods=['POST'])
def banniere_toggle(id):
    """Active/désactive une bannière."""
    banniere = Banniere.query.get_or_404(id)
    banniere.actif = not banniere.actif
    db.session.commit()
    statut = 'activée' if banniere.actif else 'désactivée'
    flash(f'Bannière "{banniere.nom}" {statut}.', 'info')
    return redirect(url_for('bannieres_list'))


@app.route('/bannieres/<int:id>/supprimer', methods=['POST'])
def banniere_supprimer(id):
    """Supprime une bannière."""
    banniere = Banniere.query.get_or_404(id)
    nom = banniere.nom
    if os.path.exists(banniere.image_path):
        os.remove(banniere.image_path)
    db.session.delete(banniere)
    db.session.commit()
    flash(f'Bannière "{nom}" supprimée.', 'info')
    return redirect(url_for('bannieres_list'))


@app.route('/clic/<int:banniere_id>')
def banniere_clic(banniere_id):
    """Tracking des clics sur bannière et redirection."""
    banniere = Banniere.query.get_or_404(banniere_id)
    banniere.nb_clics += 1
    db.session.commit()
    return redirect(banniere.lien_url)


# ---------------------------------------------------------------------------
# Routes — Paramètres
# ---------------------------------------------------------------------------

@app.route('/parametres')
def parametres():
    """Page de paramètres."""
    sync = _get_outlook_sync()
    ms_configured = sync is not None
    return render_template('parametres.html',
        entreprise=ENTREPRISE,
        ms_configured=ms_configured,
    )


@app.route('/parametres/entreprise', methods=['POST'])
def parametres_entreprise():
    """Met à jour les paramètres de l'entreprise."""
    ENTREPRISE['nom'] = request.form.get('nom', ENTREPRISE['nom'])
    ENTREPRISE['site'] = request.form.get('site', ENTREPRISE['site'])
    ENTREPRISE['logo'] = request.form.get('logo', ENTREPRISE['logo'])
    flash('Paramètres entreprise mis à jour.', 'success')
    return redirect(url_for('parametres'))


@app.route('/parametres/test-outlook', methods=['POST'])
def test_outlook_connection():
    """Teste la connexion Microsoft Graph."""
    sync = _get_outlook_sync()
    if not sync:
        return jsonify({'success': False, 'message': 'API non configurée.'})
    result = sync.test_connection()
    return jsonify(result)


# ---------------------------------------------------------------------------
# API JSON (pour intégrations futures)
# ---------------------------------------------------------------------------

@app.route('/api/collaborateurs')
def api_collaborateurs():
    collabs = Collaborateur.query.filter_by(actif=True).all()
    return jsonify([c.to_dict() for c in collabs])


@app.route('/api/bannieres')
def api_bannieres():
    bannieres = Banniere.query.filter_by(actif=True).all()
    return jsonify([b.to_dict() for b in bannieres])


@app.route('/api/signature/<int:collab_id>')
def api_signature(collab_id):
    collab = Collaborateur.query.get_or_404(collab_id)
    html = generate_signature_html(collab, base_url=BASE_URL)
    return jsonify({'html': html})


@app.route('/api/signature-by-email')
def api_signature_by_email():
    """Endpoint pour le plugin Outlook : retourne la signature par email.

    Usage : GET /api/signature-by-email?email=prenom.nom@actuelia.fr
    Retourne : { "html": "<table>...</table>", "collaborateur": "Prénom Nom" }
    """
    email = request.args.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Paramètre email requis'}), 400

    collab = Collaborateur.query.filter(
        db.func.lower(Collaborateur.email) == email,
        Collaborateur.actif == True
    ).first()

    if not collab:
        return jsonify({'error': f'Aucun collaborateur trouvé avec l\'email {email}'}), 404

    html = generate_signature_html(collab, base_url=BASE_URL)
    response = jsonify({
        'html': html,
        'collaborateur': collab.nom_complet,
        'email': collab.email,
    })
    # CORS pour le plugin Outlook
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET'
    return response


# ---------------------------------------------------------------------------
# Lancement
# ---------------------------------------------------------------------------

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
