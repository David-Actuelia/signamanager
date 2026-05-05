"""Modèles de données pour le gestionnaire de signatures email."""

from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Collaborateur(db.Model):
    """Un collaborateur de l'entreprise."""
    __tablename__ = 'collaborateurs'

    id = db.Column(db.Integer, primary_key=True)
    prenom = db.Column(db.String(100), nullable=False)
    nom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    poste = db.Column(db.String(200), nullable=False)
    telephone = db.Column(db.String(50))
    mobile = db.Column(db.String(50))
    photo_url = db.Column(db.String(500))
    linkedin_url = db.Column(db.String(500))
    departement = db.Column(db.String(100))
    actif = db.Column(db.Boolean, default=True)
    template_id = db.Column(db.Integer, db.ForeignKey('templates_signature.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    template = db.relationship('TemplateSignature', backref='collaborateurs')

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"

    def to_dict(self):
        return {
            'id': self.id,
            'prenom': self.prenom,
            'nom': self.nom,
            'nom_complet': self.nom_complet,
            'email': self.email,
            'poste': self.poste,
            'telephone': self.telephone,
            'mobile': self.mobile,
            'photo_url': self.photo_url,
            'linkedin_url': self.linkedin_url,
            'departement': self.departement,
            'actif': self.actif,
            'template_id': self.template_id,
        }


class TemplateSignature(db.Model):
    """Un modèle de signature email."""
    __tablename__ = 'templates_signature'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    html_template = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'description': self.description,
            'is_default': self.is_default,
        }


class Banniere(db.Model):
    """Une bannière promotionnelle cliquable."""
    __tablename__ = 'bannieres'

    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(200), nullable=False)
    image_path = db.Column(db.String(500), nullable=False)
    lien_url = db.Column(db.String(500), nullable=False)
    alt_text = db.Column(db.String(200))
    date_debut = db.Column(db.Date, nullable=False, default=date.today)
    date_fin = db.Column(db.Date)
    actif = db.Column(db.Boolean, default=True)
    ordre = db.Column(db.Integer, default=0)
    nb_clics = db.Column(db.Integer, default=0)
    nb_affichages = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def est_active_aujourdhui(self):
        today = date.today()
        if not self.actif:
            return False
        if self.date_debut and self.date_debut > today:
            return False
        if self.date_fin and self.date_fin < today:
            return False
        return True

    @property
    def taux_clic(self):
        if self.nb_affichages == 0:
            return 0
        return round((self.nb_clics / self.nb_affichages) * 100, 2)

    def to_dict(self):
        return {
            'id': self.id,
            'nom': self.nom,
            'image_path': self.image_path,
            'lien_url': self.lien_url,
            'alt_text': self.alt_text,
            'date_debut': self.date_debut.isoformat() if self.date_debut else None,
            'date_fin': self.date_fin.isoformat() if self.date_fin else None,
            'actif': self.actif,
            'est_active': self.est_active_aujourdhui,
            'nb_clics': self.nb_clics,
            'nb_affichages': self.nb_affichages,
            'taux_clic': self.taux_clic,
        }


class DeploiementLog(db.Model):
    """Log de déploiement de signature vers Outlook."""
    __tablename__ = 'deploiement_logs'

    id = db.Column(db.Integer, primary_key=True)
    collaborateur_id = db.Column(db.Integer, db.ForeignKey('collaborateurs.id'))
    statut = db.Column(db.String(20))  # 'succes', 'erreur'
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    collaborateur = db.relationship('Collaborateur', backref='deploiements')
