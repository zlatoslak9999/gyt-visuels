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
    r = appel('me/media_publish', {'creation_id': c['id']}, True)
    return r.get('id'), r.get('erreur')


def verifier(mid):
    for _ in range(3):
        v = appel(mid, {'fields': 'id,permalink,media_product_type'})
        if v.get('id') and (v.get('permalink') or v.get('media_product_type') == 'STORY'):
            return v
        time.sleep(4)
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
