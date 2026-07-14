# 🏦 Bank Statement Extractor

Application web Streamlit pour extraire automatiquement les données
des relevés bancaires PDF et les exporter en Excel ou CSV.

## ✨ Fonctionnalités

- 📄 **Upload PDF** par glisser-déposer
- 🔍 **Extraction automatique** (PDF natif + OCR pour PDF scannés)
- 📊 **Tableau interactif** avec recherche et pagination
- 📈 **Graphique** d'évolution du solde
- ✏️ **Éditeur manuel** intégré
- 📥 **Export Excel** formaté avec mise en forme professionnelle
- 📄 **Export CSV** compatible Excel
- 🧮 **Statistiques** : total crédits, débits, flux net

## 🏦 Banques supportées

| Banque | Type PDF | Statut |
|--------|----------|--------|
| Financial House S.A | Natif + Scanné | ✅ |
| Autres banques | Natif | ⚠️ (partiel) |

## 🚀 Installation locale

### Prérequis

- Python 3.9+
- Tesseract OCR
- Poppler

### 1. Cloner le dépôt

```bash
git clone https://github.com/votre-username/bank-extractor-streamlit.git
cd bank-extractor-streamlit
```

### 2. Créer un environnement virtuel

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Installer les dépendances Python

```bash
pip install -r requirements.txt
```

### 4. Installer les dépendances système

**Ubuntu/Debian :**
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-fra poppler-utils
```

**macOS :**
```bash
brew install tesseract tesseract-lang poppler
```

**Windows :**
- Tesseract : https://github.com/UB-Mannheim/tesseract/wiki
- Poppler : https://github.com/oschwartz10612/poppler-windows/releases

### 5. Lancer l'application

```bash
streamlit run app.py
```

Ouvrez votre navigateur sur : `http://localhost:8501`

## ☁️ Déploiement Streamlit Cloud

1. Pushez ce dépôt sur GitHub
2. Connectez-vous sur [share.streamlit.io](https://share.streamlit.io)
3. Cliquez **New app**
4. Sélectionnez votre dépôt → branche `main` → fichier `app.py`
5. Cliquez **Deploy**

> ✅ Les fichiers `requirements.txt` et `packages.txt` sont
> automatiquement détectés par Streamlit Cloud.

## 📁 Structure du projet

```
bank-extractor-streamlit/
│
├── app.py              # Application Streamlit principale
├── extractor.py        # Extraction PDF (natif + OCR)
├── cleaner.py          # Nettoyage et statistiques
├── exporter.py         # Export Excel/CSV
├── requirements.txt    # Dépendances Python
├── packages.txt        # Dépendances système (Streamlit Cloud)
├── .streamlit/
│   └── config.toml     # Thème et configuration
├── .gitignore
└── README.md
```

## 🔧 Configuration

Modifiez `.streamlit/config.toml` pour personnaliser le thème :

```toml
[theme]
primaryColor = "#1F4E79"
backgroundColor = "#F0F4F8"
```

## 📸 Aperçu

| Écran | Description |
|-------|-------------|
| Upload | Glisser-déposer le PDF |
| Extraction | Barre de progression en temps réel |
| Résultats | Tableau avec stats, recherche, export |

## 🤝 Contribution

Les contributions sont les bienvenues !

```bash
git checkout -b feature/ma-fonctionnalite
git commit -m "feat: description"
git push origin feature/ma-fonctionnalite
```

## 📄 Licence

MIT License — voir `LICENSE`
