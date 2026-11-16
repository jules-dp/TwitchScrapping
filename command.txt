# Ajouter des streamers à la main (les logins introuvables sont signalés)
python twitch_clips.py add squeezie kamet0 gotaga zerator

# Ou remplir la base automatiquement avec les streamers FR en live (> 200 viewers)
python twitch_clips.py discover --pages 3 --min-viewers 200

# Récupérer les clips des 48 dernières heures
python twitch_clips.py collect

# Télécharger les 20 meilleurs clips (≥ 20 vues, ≤ 60 s)
python twitch_clips.py download

# Voir l'état de la base
python twitch_clips.py stats

