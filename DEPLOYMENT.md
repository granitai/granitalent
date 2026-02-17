# Guide de Déploiement Docker

Ce guide explique comment déployer l'application AI Interview sur un serveur distant avec Docker.

## 📋 Prérequis

- Docker et Docker Compose installés sur le serveur
- Fichier `.env` configuré dans `backend/` avec toutes les clés API

## 🚀 Déploiement

### 1. Préparer le serveur

```bash
# Installer Docker et Docker Compose
sudo apt update
sudo apt install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker

# Vérifier l'installation
docker --version
docker-compose --version
```

### 2. Transférer le projet sur le serveur

**Option A : Via Git**
```bash
git clone <votre-repo> /opt/ai-interview
cd /opt/ai-interview
```

**Option B : Via SCP (depuis votre machine locale)**
```bash
scp -r ./AI_Interview user@server:/opt/
ssh user@server
cd /opt/AI_Interview
```

### 3. Configurer les variables d'environnement

```bash
cd backend
nano .env
```

Assurez-vous que le fichier `.env` contient :
```env
ELEVENLABS_API_KEY=votre_clé_elevenlabs
GOOGLE_API_KEY=votre_clé_google
CARTESIA_API_KEY=votre_clé_cartesia
OPENAI_API_KEY=votre_clé_openai
JWT_SECRET_KEY=une_clé_secrète_très_longue_et_aléatoire
VOICE_ID=cjVigY5qzO86Huf0OWal
CARTESIA_VOICE_ID=79a125e8-cd45-4c13-8a67-188112f4dd22
```

### 4. Construire et démarrer les conteneurs

```bash
# Revenir à la racine du projet
cd /opt/ai-interview

# Construire les images Docker
docker-compose build

# Démarrer les services
docker-compose up -d

# Vérifier que tout fonctionne
docker-compose ps
docker-compose logs -f
```

### 5. Configurer le firewall

```bash
# Autoriser le port 80 (frontend)
sudo ufw allow 80/tcp

# Optionnel : autoriser le port 8000 (backend direct)
sudo ufw allow 8000/tcp

# Vérifier le statut
sudo ufw status
```

### 6. Accéder à l'application

- **Frontend** : `http://IP_DU_SERVEUR`
- **API Backend** : `http://IP_DU_SERVEUR/api`
- **Documentation API** : `http://IP_DU_SERVEUR/docs`

Pour trouver l'IP du serveur :
```bash
# IP publique
curl ifconfig.me

# Ou IP locale
hostname -I
```

## 🔧 Commandes utiles

### Voir les logs
```bash
# Tous les services
docker-compose logs -f

# Backend uniquement
docker-compose logs -f backend

# Frontend uniquement
docker-compose logs -f frontend
```

### Redémarrer les services
```bash
docker-compose restart
```

### Arrêter les services
```bash
docker-compose down
```

### Reconstruire après modifications
```bash
docker-compose up -d --build
```

### Accéder au shell du backend
```bash
docker-compose exec backend bash
```

### Vérifier l'état des conteneurs
```bash
docker-compose ps
```

## 🐛 Dépannage

### Les conteneurs ne démarrent pas
```bash
# Vérifier les logs
docker-compose logs

# Vérifier que le fichier .env existe
ls -la backend/.env
```

### Erreur de connexion à la base de données
- Vérifier que le volume `database.db` est bien monté
- Les permissions peuvent être un problème : `sudo chmod 666 backend/database.db`

### Le frontend ne charge pas
- Vérifier que le port 80 est ouvert : `sudo ufw status`
- Vérifier les logs Nginx : `docker-compose logs frontend`

### L'API ne répond pas
- Vérifier que le backend est démarré : `docker-compose ps`
- Vérifier les logs : `docker-compose logs backend`
- Tester directement : `curl http://localhost:8000/docs`

## 📝 Notes importantes

- **Développement local** : Vous pouvez toujours utiliser `npm run dev` sur votre machine locale pour le développement. Les modifications sont compatibles avec les deux environnements.
- **Base de données** : La base de données SQLite est persistée dans `backend/database.db` via un volume Docker.
- **Variables d'environnement** : Ne jamais commiter le fichier `.env` dans Git.
- **CORS** : En production, vous pouvez restreindre les origines autorisées dans `backend/main.py` ligne 96.

## 🔄 Mise à jour

Pour mettre à jour l'application après des modifications :

```bash
# Arrêter les services
docker-compose down

# Récupérer les dernières modifications (si Git)
git pull

# Reconstruire et redémarrer
docker-compose up -d --build
```

