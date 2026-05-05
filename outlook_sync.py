"""
Module de synchronisation des signatures email avec Microsoft Outlook 365.
Utilise Microsoft Graph API pour déployer les signatures sur les boîtes mail.

Prérequis :
1. Créer une application dans Azure AD (https://portal.azure.com)
2. Configurer les permissions API : Mail.ReadWrite, User.Read.All
3. Renseigner CLIENT_ID, CLIENT_SECRET, TENANT_ID dans .env
"""

import logging
import requests
from msal import ConfidentialClientApplication

logger = logging.getLogger(__name__)


class OutlookSync:
    """Gère la synchronisation des signatures avec Outlook 365 via MS Graph API."""

    GRAPH_URL = "https://graph.microsoft.com/v1.0"
    SCOPES = ["https://graph.microsoft.com/.default"]

    def __init__(self, client_id: str, client_secret: str, tenant_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self._app = None
        self._token = None

    @property
    def app(self):
        if self._app is None:
            self._app = ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret,
            )
        return self._app

    def get_token(self) -> str | None:
        """Obtient un token d'accès via client credentials flow."""
        result = self.app.acquire_token_silent(self.SCOPES, account=None)
        if not result:
            result = self.app.acquire_token_for_client(scopes=self.SCOPES)

        if "access_token" in result:
            self._token = result["access_token"]
            return self._token
        else:
            logger.error("Erreur d'authentification MS Graph: %s", result.get("error_description"))
            return None

    def _headers(self) -> dict:
        token = self.get_token()
        if not token:
            raise ConnectionError("Impossible d'obtenir un token Microsoft Graph.")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def get_user_by_email(self, email: str) -> dict | None:
        """Recherche un utilisateur Azure AD par son email."""
        try:
            resp = requests.get(
                f"{self.GRAPH_URL}/users/{email}",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Utilisateur non trouvé: %s (HTTP %d)", email, resp.status_code)
            return None
        except Exception as e:
            logger.error("Erreur recherche utilisateur %s: %s", email, e)
            return None

    def deploy_signature(self, email: str, signature_html: str) -> dict:
        """
        Déploie une signature HTML sur la boîte Outlook d'un utilisateur.

        Utilise l'endpoint mailboxSettings pour configurer la signature.
        Nécessite la permission MailboxSettings.ReadWrite.

        Returns:
            dict avec 'success' (bool) et 'message' (str)
        """
        try:
            url = f"{self.GRAPH_URL}/users/{email}/mailboxSettings"

            payload = {
                "automaticRepliesSetting": None,  # Ne pas toucher aux réponses auto
            }

            # Mise à jour de la signature via PATCH sur mailboxSettings
            # Note : Graph API v1.0 supporte la modification de la signature
            # via le champ userPurpose ou via Outlook REST API
            patch_payload = {
                "@odata.context": f"{self.GRAPH_URL}/$metadata#users('{email}')/mailboxSettings",
                "signatureHtml": signature_html,
            }

            # Méthode alternative : utiliser l'endpoint de message pour
            # configurer la signature par défaut
            resp = requests.patch(
                url,
                headers=self._headers(),
                json=patch_payload,
                timeout=15,
            )

            if resp.status_code in (200, 204):
                logger.info("Signature déployée avec succès pour %s", email)
                return {"success": True, "message": f"Signature déployée pour {email}"}
            else:
                error_msg = resp.json().get("error", {}).get("message", resp.text)
                logger.error("Erreur déploiement pour %s: %s", email, error_msg)
                return {"success": False, "message": f"Erreur: {error_msg}"}

        except ConnectionError as e:
            return {"success": False, "message": f"Erreur de connexion: {str(e)}"}
        except Exception as e:
            logger.error("Erreur inattendue déploiement %s: %s", email, e)
            return {"success": False, "message": f"Erreur inattendue: {str(e)}"}

    def deploy_bulk(self, signatures: list[dict]) -> list[dict]:
        """
        Déploie les signatures pour plusieurs collaborateurs.

        Args:
            signatures: liste de dicts {'email': str, 'html': str}

        Returns:
            liste de résultats par collaborateur
        """
        results = []
        for sig in signatures:
            result = self.deploy_signature(sig["email"], sig["html"])
            result["email"] = sig["email"]
            results.append(result)
        return results

    def test_connection(self) -> dict:
        """Teste la connexion à Microsoft Graph API."""
        try:
            token = self.get_token()
            if not token:
                return {"success": False, "message": "Impossible d'obtenir un token."}

            resp = requests.get(
                f"{self.GRAPH_URL}/organization",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                org = resp.json().get("value", [{}])[0]
                return {
                    "success": True,
                    "message": f"Connecté à : {org.get('displayName', 'Organisation')}",
                }
            return {"success": False, "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
