# Mon premier programme Python
print("Bonjour ! Bienvenue dans la gestion de cave.")

# Les variables
nom_cave = "Cave du Coin"
nombre_produits = 250
prix_moyen = 1500

# Afficher les informations
print(f"Cave : {nom_cave}")
print(f"Nombre de produits : {nombre_produits}")
print(f"Prix moyen : {prix_moyen} FCFA")

# Un petit calcul
valeur_totale = nombre_produits * prix_moyen
print(f"Valeur totale du stock : {valeur_totale:,} FCFA")

# Exercice : calculer la valeur moyenne par catégorie
nombre_de_categorie = 3
valeur_moyenne_par_categorie = valeur_totale / nombre_de_categorie
print(f"Valeur moyenne par catégorie : {valeur_moyenne_par_categorie:,.0f} FCFA")