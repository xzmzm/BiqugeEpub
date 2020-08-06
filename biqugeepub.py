#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'hipro'
__version__ = '2013.12.19'
__license__ = 'GPL'

import gzip
import logging
import os.path
import re
import os

from datetime import datetime
from sys import argv, exit as esc
from urllib.request import urlopen, Request
from urllib.parse import quote
from shutil import copytree, rmtree
from zipfile import ZipFile, ZIP_DEFLATED
from io import BytesIO

logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
if not os.path.exists(logs_dir):
    os.mkdir(logs_dir)
formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
log_FileHandler = logging.FileHandler(filename=os.path.join(os.path.dirname(__file__), 'logs',
                                                            (datetime.now().strftime('%Y%m%d')) + '_biquge_epub.log'))

log_FileHandler.setFormatter(formatter)
log_FileHandler.setLevel(logging.DEBUG)
logger = logging.getLogger()
logger.addHandler(log_FileHandler)
logger.setLevel(logging.DEBUG)


class BiqugeEpub(object):
    def __init__(self, book_name):
        self.site = 'www.biquge.info'
        self.book_name = book_name
        self.author = ''
        if '@' in book_name:
            self.book_name, self.author = self.win_unencode(book_name).split('@')[:2]
        self.book_id = '0'
        self.book_id_f = '0'

    @staticmethod
    def open_url(url, bytes_like=False):
        """获取页面内容"""
        headers = {
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
                'DNT': '1',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/83.0.4103.116 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,'
                          '*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'Sec-Fetch-Dest': 'document',
                'Accept-Language': 'en-US,en;q=0.9,zh;q=0.8,zh-CN;q=0.7',
                'Cookie': '',
            }
        if 'baidu' in url:
            headers['Cookie'] = 'BIDUPSID=E8EB36E723A652727DEEC0EB3EA57F65; PSTM=1596351458; ' \
                                'BAIDUID=E8EB36E723A65272C365B5BA3F6CB761:FG=1; BD_UPN=123353; ' \
                                'BDORZ=B490B5EBF6F3CD402E515D22BCDA1598; delPer=0; BD_CK_SAM=1; PSINO=6; ' \
                                'COOKIE_SESSION=10201_0_7_2_5_1_1_0_7_1_1_0_6686_0_0_0_1596358447_0_15' \
                                '96370817%7C9%230_0_1596370817%7C1; ZD_ENTRY=baidu;' \
                                ' H_PS_645EC=2123NmsIsgx%2B0V8k%2BQt2%2BhVyIFpvYBhXRUdk12IjKRSlBiumY34rGozrLqA; ' \
                                'BDSVRTM=126; H_PS_PSSID=32292_1454_31669_32358_32328_31660_32350_32045_32394_3' \
                                '2429_32117_32091_26350_31639'

        req = Request(url, headers=headers)
        body = ''
        try:
            resp = urlopen(req, None, timeout=60)
            if resp.code == 200:
                body = resp.read()
                if body[:6] == b'\x1f\x8b\x08\x00\x00\x00':  # gzip
                    body = gzip.GzipFile(fileobj=BytesIO(body)).read()

                # logging.info(type(body)
                if (not bytes_like) and isinstance(body, bytes):
                    body = body.decode('utf-8', 'ignore')
                # logging.info(body)
        except Exception as e:
            logging.exception(e)
        return body

    def query_book_info(self):
        """获取小说id"""
        site_pattern = self.site.replace('.', r'\.') + '/([0-9]{1,2})_([0-9]{1,9})/'
        query_operator = 'site:%s+intitle:"%s"' % (self.site.replace("www.", ''), quote(self.book_name))

        def query(query_url):
            for key in ('最新章节', '全文阅读'):  # 精确匹配，防止下载错误小说。
                url = ''.join([query_url, query_operator, quote(key)])
                logging.info(url)
                body = self.open_url(url)
                result = re.search(site_pattern, body)
                if result:
                    return result

        baidu_query_url = 'https://www.baidu.com/s?rn=5&wd='
        book_link = query(baidu_query_url)
        if book_link is None:  # 用google再试一次。
            google_query_url = "https://www.google.com.hk/search?num=5&q="
            book_link = query(google_query_url)

        if book_link:
            self.book_id_f = book_link.group(1)
            self.book_id = book_link.group(2)
            _book_url = book_link.group(0)
            book_info = {
                'author': '',
                'author_url': '',  # 'https://www.google.com.hk/search?num=1&q=%s'
                'book_id': self.book_id,
                'book_name': self.book_name,
                'book_url': _book_url if 'http://' in _book_url else "http://" + _book_url,
                'description': '',
                'img_url': 'http://www.biquge.info/files/article/image/%(book_id_f)s/%(book_id)s/%(book_id)ss.jpg' %
                           {
                               'book_id_f': self.book_id_f,
                               'book_id': self.book_id,
                           },
                'rights': 'Copyright (C) 书籍内容由用户自行采集于网络，用于轻度阅读。'
                          '版权归原作者及原发布网站所有，不得用于商业复制、下载、传播',
                'site': 'www.biquge.info',
                'site_name': '笔趣阁',
                'site_abbr': '本书',
                'site_pinyin': 'biquge',
                'subject': '小说',
            }

            logging.info("book_url: %s" % book_info['book_url'])
            return book_info
        else:
            logging.info('Could not find %s.' % self.win_encode(self.book_name))
            return

    @staticmethod
    def win_encode(uni_str):
        if os.name == 'nt':
            return uni_str.decode('utf-8', 'ignore').encode('gbk', 'ignore')
        else:
            return uni_str

    @staticmethod
    def win_unencode(win_str):
        if os.name == 'nt':
            return win_str.decode('gbk', 'ignore').encode('utf-8', 'ignore')
        else:
            return win_str

    def generate_epub(self):
        book_info = self.query_book_info()
        if not book_info:
            return
        # open book site, get book info.
        body = self.open_url(book_info['book_url'])
        body = self.win_unencode(body)
        if len(body) > 100:
            logging.info('=== Retrieving book information.')

        subject = re.search('<p>类&nbsp;&nbsp;&nbsp;&nbsp;别:(.+?)小说</p>', body, re.U)
        if subject:
            book_info['subject'] = subject.group(1)
        logging.info('Subject: %s' % self.win_encode(book_info.get('subject')))

        author = re.search('<p>作&nbsp;&nbsp;&nbsp;&nbsp;者:(.+?)</p>', body, re.U)
        if author:
            book_info['author'] = author.group(1).strip()
            # book_info['author_url'] = book_info['author_url'] % book_info['author']
        logging.info('author: %s' % self.win_encode(book_info.get('author')))
        if self.author and self.author != book_info['author']:
            logging.info('not the author: %s')
            return

        description = re.search('<div id="intro">\\s+<p>(.+?)</p>.+?</div>', body, re.U | re.S)
        if description:
            book_info['description'] = \
                description.group(1).strip().replace(' ',
                                                     '').replace('&nbsp;',
                                                                 '').replace('<br>', '').replace('<br/>', '')
        logging.info('description: %s' % self.win_encode(book_info.get('description')))

        updated = re.search('<p>最后更新&nbsp;&nbsp;:(.+?)</p>', body, re.U | re.S)
        if updated:
            book_info['updated'] = updated.group(1).strip()
        else:
            book_info['updated'] = ''
        logging.info('last update: %s' % self.win_encode(book_info.get('updated')))

        # <a href="1818809.html" title="第七章 修炼">第七章 修炼</a>
        chapters = re.findall(r'<a href="([0-9]{1,9})\.html" title=".+?">(.+?)</a>', body, re.U)
        del body

        # # Remove the cache 9 chapters.
        # if len(chapters)>9: del chapters[:9]
        logging.info('Total Chapters: %s', len(chapters))

        resume = 0  # 断章续传，记录上次中断时，下载到了哪一章。
        log_path = '%s/log' % self.book_id
        if os.path.exists(self.book_id):
            if os.path.exists(log_path):
                with open(log_path, 'r') as log:
                    resume = int(log.read())
                    os.remove(log_path)
            else:
                rmtree(self.book_id)
                logging.info('=== Remove old files.')
        else:
            # copy template                    
            copytree('epub_template', self.book_id)
        os.chdir(self.book_id)

        epub_name = self.win_encode(self.book_name + '-' + book_info['author'] + '.epub')
        epub_path = '../' + epub_name
        if os.path.exists(epub_path):
            os.remove(epub_path)

        try:
            # create foundation documents.            
            logging.info('=== Creating the foundation documents.')
            content_html = open('content.html', 'r')
            temp_con = content_html.read()
            content_html.close()
            base_url = 'http://' + self.site + '/%(book_id_f)s_%(book_id)s/content.html' % {
                'book_id_f': self.book_id_f, 'book_id': book_info['book_id']}

            for chapter in chapters[resume:]:
                # http://www.biquge.info/77_77004/19481378.html
                body = self.win_unencode(self.open_url(base_url.replace('content', chapter[0])))
                content = re.search('<div id="content">(.+?)</div>', body, re.U | re.S)

                content = content.group(1). \
                    replace('\r\n', '').replace(' ', '').replace('&nbsp;', '').replace("<br />", "<br/>")
                content = re.sub('&amp.*;', '', content)
                content = re.sub('(<|&lt;)a.+?(<|&lt;)/a(>|&gt;)', '', content, re.U | re.S)
                content = re.sub(r'(\(|（).*(\)|）)', '', content, re.U | re.S)
                content = re.sub('^(.*);$', lambda x: x.group(1), content, re.U | re.S)
                content = content.replace("<br/><br/>", "</p><p>")
                content = "".join(["<p>", content, "</p>"])

                write_content = temp_con.replace("{{title}}", chapter[1]).replace("{{content}}", content)

                content_id = "content%s_%s" % (self.book_id, chapter[0])
                with open('.'.join([content_id, 'html']), 'w') as f:  # create content.html
                    f.write(write_content)

                resume += 1

            del temp_con
            os.remove('content.html')

            render_for = {
                'item_list': ['<item id="%(content_id)s" href="%(content_id)s.html" '
                              'media-type="application/xhtml+xml" />', ],
                'itemref_list': ['<itemref idref="%(content_id)s" />', ],
                'navPointlist': ['<navPoint id="%(content_id)s" playOrder="%(no)s"><navLabel>'
                                 '<text>%(title)s</text></navLabel><content '
                                 'src="%(content_id)s.html"/></navPoint>', ],
                'chapter_list': ['<li%(even_class_flag)s><a href="%(content_id)s.html">%(title)s</a></li>', ],
            }
            no = 3  # playOrder for ncx.

            for chapter in chapters:
                content_id = "content%s_%s" % (self.book_id, chapter[0])
                no += 1
                even_class_flag = ('', ' class="even"')[(no - 3) % 2]  # for css

                render_for['item_list'].append(render_for['item_list'][0] % {'content_id': content_id})
                render_for['itemref_list'].append(render_for['itemref_list'][0] % {'content_id': content_id})
                render_for['navPointlist'].append(render_for['navPointlist'][0] % {'content_id': content_id,
                                                                                   'title': chapter[1],
                                                                                   'no': str(no)})
                render_for['chapter_list'].append(render_for['chapter_list'][0] % {'content_id': content_id,
                                                                                   'title': chapter[1],
                                                                                   'even_class_flag': even_class_flag})

            del chapters

            # add page site.
            no += 1
            even_class_flag = ('', ' class="even"')[(no - 3) % 2]
            render_for['chapter_list'].append(render_for['chapter_list'][0].replace('html', 'xhtml') %
                                              {'content_id': 'page',
                                               'title': '关于%s' % book_info['site_abbr'],
                                               'even_class_flag': even_class_flag})
            render_for['navPointlist'].append(render_for['navPointlist'][0].replace('html', 'xhtml') %
                                              {'content_id': 'page',
                                               'title': '关于%s' % book_info['site_abbr'],
                                               'no': str(no)})

            def render(f_str):
                if '%' in f_str:
                    f_str = f_str.replace('%', '%%')
                f_str = re.sub(r'(\{\{[a-z_]{1,20}\}\})',
                               lambda x: "".join(['%', '(', x.group(1)[2:-2], ')', 's']), f_str, re.U)
                f_str = f_str % book_info
                if '%%' in f_str:
                    f_str = f_str.replace('%%', '%')
                return f_str

            # catalog.html, toc.ncx, content.opf, title.xhtml
            with open('catalog.html', 'r+') as cat_t, open('toc.ncx', 'r+') as toc_t, \
                    open('content.opf', 'r+') as con_t, open('title.xhtml', 'r+') as tit_t:

                tit_str = tit_t.read()
                tit_str = tit_str.replace('\r', "")
                tit_t.seek(0)
                tit_t.write(render(tit_str))
                del tit_str

                cat_str = cat_t.read()
                cat_str = cat_str.replace('\r', "")
                cat_t.seek(0)

                toc_str = toc_t.read()
                toc_t.seek(0)

                con_str = con_t.read()
                con_t.seek(0)

                cat_str = cat_str.replace('{{for_chapter_list}}', "\n".join(render_for['chapter_list'][1:]))
                cat_t.write(render(cat_str))
                del cat_str
                toc_str = toc_str.replace('{{for_navPointlist}}', "".join(render_for['navPointlist'][1:]))
                toc_t.write(render(toc_str))
                del toc_str
                con_str = con_str.replace('{{for_item_list}}', "".join(render_for['item_list'][1:]))
                con_str = con_str.replace('{{for_itemref_list}}', "".join(render_for['itemref_list'][1:]))
                con_t.write(render(con_str))
                del con_str

            del render_for

            # get cover.jpg 
            with open('cover.jpg', 'wb') as jpg:
                jpg.write(self.open_url(book_info['img_url'], bytes_like=True))

            logging.info('=== Being generated.')
            # zip *.epub
            with ZipFile(epub_path, 'w', ZIP_DEFLATED) as z:
                for b, ds, fs in os.walk('.'):
                    for ff in fs:
                        z.write(os.path.join(b, ff))

        except Exception as e:
            with open('log', 'w') as log:
                log.write(str(resume))

            logging.info('Fail!')
            logging.info('\n=======')
            logging.exception(e)
            logging.info('=======\n')
            logging.info("Test whether you can read this novel on < %s > with your browser. "
                         "If it's okay, you can re-run program again or feedback this issue to "
                         "< https://github.com/hipro/BiqugeEpub >." % self.site)
        else:
            logging.info('=== Cleaned temp files.')
            # if os.path.split(os.getcwd())[-1] == self.book_id:
            os.chdir("../.")
            rmtree(self.book_id)

            logging.info('=== Finish!')
            logging.info('Epub file path: ./%s.' % epub_name)


def test():
    _epub = BiqugeEpub("凡人修仙传")
    # epub.query_book_info()
    epub.generate_epub()


if __name__ == '__main__':
    if len(argv) < 2:
        info = '''Input args error, please type: "%(script)s Book_Name_You_Want".'''
        esc(info % {'script': argv[0]})
    else:
        logging.info(argv[1])
        epub = BiqugeEpub(argv[1])
        epub.generate_epub()
