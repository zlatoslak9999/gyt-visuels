"""Lancé par GitHub Actions toutes les 15 minutes (dépôt gyt-visuels) : publie sur Instagram les entrées de planning.json
arrivées à l'heure (heure de Paris), avec la story si demandée, vérifie chaque publication chez Instagram et note le résultat.
Le cockpit GYT écrit planning.json (Planifier, Envoyer sur GitHub) et relit les résultats."""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

IG = 'https://graph.instagram.com/v21.0/'
TOKEN = os.environ.get('IG_TOKEN', '')


def appel(chemin, q, poster=False):
    q['access_token'] = TOKEN
    try:
        req = urllib.request.Request(IG + chemin, data=urllib.parse.urlencode(q).encode(), method='POST') if poster else IG + chemin + '?' + urllib.parse.urlencode(q)
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        try:
            return {'erreur': json.load(e).get('error', {}).get('message', '')[:200] or f'HTTP {e.code}'}
        except ValueError:
            return {'erreur': f'HTTP {e.code}'}
    except OSError as e:
        return {'erreur': f'Instagram ne répond pas ({e.__class__.__name__})'}


def publier(params):
    c = appel('me/media', params, True)
    if c.get('erreur'):
        return None, c['erreur']
    for _ in range(20):
        e = appel(c['id'], {'fields': 'status_code'})
        if e.get('status_code') == 'FINISHED':
            break
        if e.get('status_code') == 'ERROR' or e.get('erreur'):
            return None, e.get('erreur') or 'Instagram n’a pas pu lire l’image'
        time.sleep(3)
    else:
        return None, 'Instagram traite encore l’image'
    for _essai in range(5):  # 06/11 : « Media ID is not available » = Instagram pas encore prêt → on réessaie
        r = appel('me/media_publish', {'creation_id': c['id']}, True)
        if not (r.get('erreur') and 'not available' in r['erreur']):
            break
        time.sleep(6)
    return r.get('id'), r.get('erreur')


def carrousel_params(images, legende):
    """05/11 soir : carrousel = 2 à 10 images. Renvoie (paramètres de chaque page, paramètres du conteneur parent sans 'children').
    Rien n'est envoyé ici : sert aussi au test à blanc (outils/carrousel_test.py)."""
    if not 2 <= len(images) <= 10:
        raise ValueError(f'un carrousel Instagram compte 2 à 10 images, pas {len(images)}')
    return [{'image_url': u, 'is_carousel_item': 'true'} for u in images], {'media_type': 'CAROUSEL', 'caption': (legende or '')[:2200]}


def publier_carrousel(images, legende, a_blanc=False):
    """Conteneur par page → attente du traitement → conteneur CAROUSEL (children = ids) → publication.
    a_blanc=True : s'arrête avant media_publish (rien n'est publié ; les conteneurs expirent seuls sous 24 h)."""
    pages, parent = carrousel_params(images, legende)
    ids = []
    for p in pages:
        c = appel('me/media', dict(p), True)
        if c.get('erreur'):
            return None, c['erreur']
        ids.append(c['id'])
    for i in ids:
        for _ in range(20):
            e = appel(i, {'fields': 'status_code'})
            if e.get('status_code') == 'FINISHED':
                break
            if e.get('status_code') == 'ERROR' or e.get('erreur'):
                return None, e.get('erreur') or 'Instagram n’a pas pu lire une page du carrousel'
            time.sleep(3)
    c = appel('me/media', {**parent, 'children': ','.join(ids)}, True)
    if c.get('erreur') or a_blanc:
        return (None, c['erreur']) if c.get('erreur') else ('a_blanc:' + c['id'], None)
    # 10/11 : le conteneur CAROUSEL doit lui aussi être FINISHED avant media_publish (sinon « Media ID is not available »)
    for _ in range(30):
        e = appel(c['id'], {'fields': 'status_code'})
        if e.get('status_code') == 'FINISHED':
            break
        if e.get('status_code') == 'ERROR' or e.get('erreur'):
            return None, e.get('erreur') or 'Instagram n’a pas pu assembler le carrousel'
        time.sleep(3)
    for _essai in range(6):
        r = appel('me/media_publish', {'creation_id': c['id']}, True)
        if not (r.get('erreur') and 'not available' in r['erreur']):
            break
        time.sleep(8)
    return r.get('id'), r.get('erreur')


def verifier(mid):
    for _ in range(3):
        v = appel(mid, {'fields': 'id,permalink,media_product_type'})
        if v.get('id') and (v.get('permalink') or v.get('media_product_type') == 'STORY'):
            return v
        time.sleep(4)
    return None


def tete(t):
    return ''.join(c for c in (t or '').split('\n')[0].lower() if c.isalnum())[:40]


def deja_publie(legende):
    """Post du compte publié depuis moins de 24 h avec la même première ligne de légende (anti-doublon)."""
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    for m in appel('me/media', {'fields': 'id,caption,permalink,timestamp', 'limit': 15}).get('data', []):
        if dt.datetime.strptime(m['timestamp'], '%Y-%m-%dT%H:%M:%S%z') >= limite and tete(m.get('caption')) == tete(legende):
            return m
    return None


def main():
    if not TOKEN:
        raise SystemExit('Secret IG_TOKEN absent : Settings › Secrets and variables › Actions')
    P = json.load(open('planning.json', encoding='utf-8'))
    maintenant = dt.datetime.now(ZoneInfo('Europe/Paris')).replace(tzinfo=None)
    for x in P.get('publications', []):
        if x.get('statut') != 'a_publier':
            continue
        quand = dt.datetime.fromisoformat(x['quand'])
        if quand > maintenant:
            continue
        if quand < maintenant - dt.timedelta(hours=6):  # trop tard : laissé au cockpit (« à confirmer »)
            x['statut'], x['erreur'] = 'trop_tard', 'Heure dépassée de plus de 6 h'
            continue
        if x.get('story_seule'):  # 03/11 : concerts du mois (1080×1920) = story seule, aucun post dans le fil
            sid, serr = publier({'image_url': x.get('image_story') or x['image'], 'media_type': 'STORIES'})
            ok = bool(sid and verifier(sid))
            x.update({'statut': 'publie' if ok else 'erreur', 'ig_media': sid or '', 'story_ok': ok, 'publie_le': maintenant.isoformat(timespec='minutes'),
                      'erreur': '' if ok else (serr or 'Instagram ne montre pas la story')})
            print('Story :' if ok else 'Story refusée :', x.get('titre'))
            continue
        dej = deja_publie(x.get('legende', ''))
        if dej:
            x.update({'statut': 'publie', 'ig_media': dej['id'], 'permalink': dej.get('permalink', ''), 'publie_le': maintenant.isoformat(timespec='minutes'), 'erreur': ''})
            print('Déjà sur Instagram, pas republié :', x.get('titre'), x['permalink'])
            continue
        if x.get('carrousel'):  # 05/11 soir : liste des URL des pages (couverture d'abord)
            mid, erreur = publier_carrousel(x['carrousel'], x.get('legende', ''))
        else:
            mid, erreur = publier({'image_url': x['image'], 'caption': x.get('legende', '')[:2200]})
        v = verifier(mid) if mid else None
        horodatage = maintenant.isoformat(timespec='minutes')
        if not v:
            x['statut'], x['erreur'] = 'erreur', erreur or 'Instagram ne montre pas la publication'
            continue
        x.update({'statut': 'publie', 'ig_media': mid, 'permalink': v.get('permalink', ''), 'publie_le': horodatage, 'erreur': ''})
        if x.get('story') and x.get('image_story'):
            sid, serr = publier({'image_url': x['image_story'], 'media_type': 'STORIES'})
            x['story_ok'] = bool(sid and verifier(sid))
            if not x['story_ok']:
                x['story_erreur'] = serr or 'Instagram ne montre pas la story'
        print('Publié :', x.get('titre'), x['permalink'])
    json.dump(P, open('planning.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
