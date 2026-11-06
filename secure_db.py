import os
import sys
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Charger les variables du fichier .env
load_dotenv()

DB_FILE = 'cave.db'
KEY = os.getenv('DB_ENCRYPTION_KEY')

# Si la clé n'existe pas dans le .env, on la génère
if not KEY:
    print("🔑 Génération d'une nouvelle clé de chiffrement...")
    KEY = Fernet.generate_key().decode()
    
    # Ajouter la clé au fichier .env
    with open('.env', 'a') as f:
        f.write(f"\nDB_ENCRYPTION_KEY={KEY}")
    
    print(f"✅ Clé générée et sauvegardée dans .env !")
    print("⚠️ Veuillez relancer ce script pour appliquer le chiffrement.")
    sys.exit()

cipher_suite = Fernet(KEY.encode())

def encrypt_db():
    """Chiffre la base de données"""
    if not os.path.exists(DB_FILE):
        print(f"❌ Erreur : Le fichier {DB_FILE} est introuvable.")
        return
    if os.path.exists(f"{DB_FILE}.enc"):
        print("⚠️ La base de données est déjà chiffrée (.enc existe).")
        return
    
    print(f"🔒 Chiffrement de {DB_FILE} en cours...")
    with open(DB_FILE, 'rb') as f:
        data = f.read()
    
    encrypted_data = cipher_suite.encrypt(data)
    
    with open(f"{DB_FILE}.enc", 'wb') as f:
        f.write(encrypted_data)
    
    # Supprimer le fichier original non chiffré pour sécurité maximale
    os.remove(DB_FILE)
    print("✅ Base de données chiffrée avec succès ! (Fichier .enc créé)")

def decrypt_db():
    """Déchiffre la base de données"""
    enc_file = f"{DB_FILE}.enc"
    if not os.path.exists(enc_file):
        if os.path.exists(DB_FILE):
            print("ℹ️ La base de données est déjà déchiffrée et prête à l'emploi.")
        else:
            print("❌ Aucune base de données trouvée.")
        return

    print(f"🔓 Déchiffrement de {enc_file} en cours...")
    with open(enc_file, 'rb') as f:
        encrypted_data = f.read()
    
    try:
        data = cipher_suite.decrypt(encrypted_data)
        with open(DB_FILE, 'wb') as f:
            f.write(data)
        
        # On garde le fichier .enc en backup, ou on le supprime :
        # os.remove(enc_file) 
        print("✅ Base de données déchiffrée avec succès ! (Fichier .db restauré)")
    except Exception as e:
        print(f"❌ Échec du déchiffrement ! La clé dans .env est-elle correcte ? Erreur: {e}")

if __name__ == '__main__':
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action == 'lock':
            encrypt_db()
        elif action == 'unlock':
            decrypt_db()
        else:
            print("Usage: python secure_db.py [lock|unlock]")
    else:
        print("Usage: python secure_db.py [lock|unlock]")
        print("  lock   : Chiffre la base de données (à faire quand on arrête l'app)")
        print("  unlock : Déchiffre la base de données (à faire avant de lancer l'app)")