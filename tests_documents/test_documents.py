from pathlib import Path
import sys,tempfile,unittest,zipfile,json
from lxml import etree
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
import toolkit,documents


class DocumentTests(unittest.TestCase):
    def test_paired_docx_keep_identity_links_and_evidence_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'private';toolkit.init(root,True)
            draft=documents.initial_draft(root,'example-job',['fact_education'])
            output=Path(documents.render(root,draft,['html','docx'])['directory'])
            for name in ['resume','cover-letter']:
                with self.subTest(document=name):
                    with zipfile.ZipFile(output/(name+'.docx')) as z:
                        xml=z.read('word/document.xml');tree=etree.fromstring(xml)
                        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                        text=' '.join(tree.xpath('//w:t/text()',namespaces=ns))
                        self.assertIn('Jordan Example',text);self.assertIn('25,000',text)
                        self.assertIn('https://example.invalid/portfolio',z.read('word/_rels/document.xml.rels').decode())
                        self.assertIn('Georgia',z.read('word/styles.xml').decode())
            self.assertIn('cover-letter.docx',json.loads((output/'manifest.json').read_text())['files'])


if __name__=='__main__':unittest.main()
