import datetime as dt
import json
import unittest
from unittest.mock import patch
import update_feed as feed

TITLE='Le groupe Alpha annonce une hausse de ses ventes'
BODY=('Le groupe Alpha a publié ses résultats du troisième trimestre. '
      'Le chiffre d’affaires du groupe Alpha atteint 16,96 milliards d’euros, contre 12,4 milliards un an plus tôt. '
      'Le groupe Alpha prévoit désormais une croissance de 8 % pour la totalité de son exercice. '
      'Sa trésorerie disponible atteint 3,2 milliards d’euros à la fin du mois de septembre.')

def page(free=True):
    return '<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','headline':TITLE,'articleBody':BODY,'isAccessibleForFree':free})+'</script>'

class ExtractionTests(unittest.TestCase):
    def test_paywalled_body_is_never_used(self):
        self.assertEqual(feed.article_text(page(False),TITLE,'https://www.lemonde.fr/x'),('','restricted'))

    def test_hidden_related_article_is_not_the_main_article(self):
        html='<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','headline':'Un accident dans une commune rurale','articleBody':BODY})+'</script>'
        self.assertEqual(feed.article_text(html,TITLE,'https://www.franceinfo.fr/x')[0],'')

    def test_figures_and_comparisons_are_preserved(self):
        text,access=feed.article_text(page(),TITLE,'https://www.franceinfo.fr/x')
        points=feed.key_sentences(text,TITLE)
        self.assertEqual(access,'public')
        self.assertTrue(any('16,96 milliards' in p and '12,4 milliards' in p for p in points))
        self.assertTrue(any('8 %' in p and 'prévoit' in p for p in points))
        self.assertLessEqual(sum(len(p.split()) for p in points),95)
        self.assertTrue(all(p in BODY for p in points))

    def test_suggestions_and_navigation_do_not_enter_paragraphs(self):
        markup='<nav><p>Promotion à 99 euros pour tout le monde, venez vite.</p></nav><article><p>'+BODY+'</p><aside><p>Une autre société affiche 999 milliards de pertes cette année.</p></aside></article>'
        text,_=feed.article_text(markup,TITLE,'https://www.tradingsat.com/x')
        self.assertNotIn('999',text)
        self.assertNotIn('99 euros',text)

    def test_video_boilerplate_is_excluded(self):
        text='Ce texte correspond à une transcription du reportage ci-dessus, cliquez sur la vidéo. '+BODY
        self.assertFalse(any('vidéo' in p for p in feed.key_sentences(text,TITLE)))

    def test_recent_enrichment_does_not_fetch_again(self):
        now=dt.datetime.now(dt.timezone.utc)
        item={'id':'x','provenance':'rss-excerpt','summaryInput':'same','sources':[{'url':'https://www.franceinfo.fr/x'}]}
        old=dict(item,provenance='article-extract',bullets=['Un fait','Un chiffre'],enrichedAt=now.isoformat())
        with patch('urllib.request.urlopen',side_effect=AssertionError('network should not be called')):
            result=feed.enrich_item(item,{'x':old},now,set())
        self.assertEqual(result['bullets'],old['bullets'])

if __name__=='__main__':unittest.main()
