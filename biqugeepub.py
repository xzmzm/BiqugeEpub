#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'hipro'
__version__ = '2013.12.19'
__license__ = 'GPL'

from sys import argv, exit as esc
from urllib2 import urlopen, Request, URLError
from re import findall,sub,search, U, S
from os import name,chdir,walk,remove
from os.path import join,exists
from shutil import copytree, rmtree
from zipfile import ZipFile, ZIP_DEFLATED
from time import sleep


class BiqugeEpub(object):
    """docstring for BiqugeEpub"""
    def __init__(self, book_name):
        self.site = 'www.biquge.com'
        self.book_name = self.win_unencode(book_name)
        self.book_id = '0'
        self.book_id_f='0'
    
    def open_url(self,url,TIMEOUT=60):
        """docstring for open_url"""
        # create request.
        req=Request(url)
        # define user-agent.
        user_agent='Chrome/32.0.1667.0 Safari/537.36'
        req.add_header('User-agent', user_agent)
        # get response
        resp=urlopen(req,None,TIMEOUT)
        try:
            resp=urlopen(req,None,TIMEOUT)
            # status code 200 - 'ok'.
            if resp.code==200:
                return resp.read()
            else:
                return None
        except Exception:
            print 'Time out!'
            return None
       
    def query_book_info(self):
        """docstring for query_book_id"""
        base_query_url="http://www.baidu.com/s?rn=5&wd="
        baidu_pattern='www\.biquge\.com/([0-9]{1,2})_([0-9]{1,9})/'
        query_operator='site:%s+intitle:"%s"' %(self.site.replace("www.", ''), self.book_name)
        
        def query(base_query_url,pattern):
            for qkey in ('最新章节', '全文阅读'):#精确匹配，防止下载错误小说。
                url=''.join([base_query_url,query_operator,qkey])
                #print url
                html=self.open_url(url)
                result=search(pattern,html)
                if result:
                    return result
            return None
                
        book_link=query(base_query_url,baidu_pattern)
        if book_link is None:#用google再试一次。
            gbase_query_url="https://www.google.com.hk/search?num=5&q="
            google_pattern='http://www\.biquge\.com/[0-9]{1,2}_([0-9]{1,9})/'
            book_link=query(gbase_query_url,google_pattern)
        
        book_info={}
        if book_link:
            self.book_id_f=book_link.group(1)
            self.book_id=book_link.group(2)
            book_info['bookurl']=book_link.group(0)
            print "book's url on biquge.com:",book_info['bookurl']
            if "http://" not in book_info['bookurl']: book_info['bookurl']=''.join(["http://",book_info['bookurl']])
            book_info['bookid']=book_link.group(2)
            book_info['sitename']='笔趣阁'
            #book_info['sitenameabbr']='笔趣阁'
            book_info['sitenameabbr']='本书'
            book_info['sitenamepinyin']='biquge'
            book_info['siteurl']='www.biquge.com'
            book_info['subject']='小说'
            book_info['bookname']=self.book_name
            book_info['author']=''
            book_info['authorurl']=''#'https://www.google.com.hk/search?num=1&q=%s'
            book_info['description']=''
            book_info['img_url']='http://www.biquge.com/image/%(bookidf)s/%(bookid)s/%(bookid)ss.jpg' % {'bookidf':self.book_id_f,'bookid':book_info['bookid']}
            book_info['rights']='Copyright (C) 书籍内容搜集于笔趣阁，用于轻度阅读。版权归原作者及原发布网站所有，不得用于商业复制、下载、传播'
            return book_info
        else:        
            print "Could not find book information on biquge.com. Possible <biqugecom.com> has not included %s." % self.win_encode(self.book_name)
            return None        

    def win_encode(self,uni_str):
        if name is 'nt':
            return uni_str.decode('utf-8').encode('gbk')
        else:
            return uni_str
    def win_unencode(self,win_str):
        if name is 'nt':
            return win_str.decode('gbk').encode('utf-8')
        else:
            return win_str

    def generate_epub(self):
              
        book_info=self.query_book_info()
        if not book_info:
            return None 
        # open book site, get book info.
        html=self.open_url(book_info['bookurl']).decode('gbk').encode('utf-8')
        if len(html)>100:
            print "===Retrieving book information."
        subject=search('&gt; <a href="/[a-z]{4,10}xiaoshuo/">(.+?)小说</a>  &gt;', html, U)
        if subject:
            book_info['subject']=subject.group(1)
        print "Subject :", self.win_encode(book_info.get('subject'))

        author=search('<p>作.*?者：(.+?)</p>', html, U)
        if author:
            book_info['author']=author.group(1)
            #book_info['authorurl']=book_info['authorurl'] % book_info['author']
        print "Author :", self.win_encode(book_info['author'])
        #print "Authorurl is", book_info.get('authorurl')
      
        description=search('<div id="intro">\\s+<p>(.+?)</p>.+?</div>', html, U|S)
        if description:
            book_info['description']=description.group(1).strip().replace(' ','').replace('&nbsp;','').replace('<br>','\n')
        print "Description :", self.win_encode(book_info.get('description'))

        datetime=search('<p>最后更新：(.+?)</p>', html)
        if datetime:
            book_info['datetime']=datetime.group(1).strip()
        print "Last update :", book_info.get('datetime')

        title_all=findall('<a href="/[0-9]{1,2}_[0-9]{1,9}/([0-9]{1,9})\.html">(.+?)</a>', html, U)
        del html

        # Remove the cache 9 chapters.
        if len(title_all)>9: del title_all[:9]
        print 'Total Chapters:', len(title_all)   
        
        resume=0 # 断章续传，记录上次中断时，下载到了哪一章。
        log_path='%s/log' % self.book_id
        if exists(self.book_id):
            if exists(log_path): 
                with file(log_path,'r') as log:
                    resume=int(log.read())
                    remove(log_path)
            else:
                rmtree(self.book_id)
                print "===Remove old files."
                sleep(3)
        else:
            # copy template                    
            copytree('epub_template',self.book_id)
        chdir(self.book_id)
            
        epub_path='../%s.epub' % self.win_encode(self.book_name)
        if exists(epub_path): remove(epub_path)
        
        try:    
            # create foundation documents.            
            print "===Creating the foundation documents."  
                                  
            content_html=file('content.html', 'r')
            temp_con=content_html.read()
            content_html.close() 
            
            base_url='http://www.biquge.com/%(bookidf)s_%(bookid)s/content.html' % {'bookidf':self.book_id_f,'bookid':book_info['bookid']}
            
            for title in title_all[resume:]:
                html=self.open_url(base_url.replace('content',title[0])).decode('gbk').encode('utf-8')
                content=search('<div id="content">(.+?)</div>',html,U|S)
                
                content=content.group(1).replace('\r\n','').replace(' ','')\
                                        .replace('&nbsp;','').replace("<br />","<br/>")
                content=sub('&amp.*;','',content)
                content=sub('(<|&lt;)a.+?(<|&lt;)/a(>|&gt;)','',content, U|S)
                content=sub(u'(\(|（).*(\)|）)','',content, U|S)
                content=sub('^(.*);$',lambda x:x.group(1),content, U|S)
                content=content.replace("<br/><br/>","</p><p>")
                content="".join(["<p>",content,"</p>"])
                
                write_content=temp_con.replace("{{title}}",title[1]).replace("{{content}}",content)
                
                contentid="content%s_%s" % (self.book_id, title[0])
                f=file('.'.join([contentid,'html']),'w')# create content.html
                f.write(write_content)
                f.close()
                resume+=1
                
            del temp_con
            remove('content.html')
            
            render_for={
                        'itemlist':['<item id="%(contentid)s" href="%(contentid)s.html" media-type="application/xhtml+xml" />',],
                        'itemreflist':['<itemref idref="%(contentid)s" />',],
                        'navPointlist':['<navPoint id="%(contentid)s" playOrder="%(no)s"><navLabel><text>%(title)s</text></navLabel><content src="%(contentid)s.html"/></navPoint>',],
                        'titlelist':['<li%(even_class_flag)s><a href="%(contentid)s.html">%(title)s</a></li>',],
                        }
            no=3 # playOrder for ncx.
            
            for title in title_all:
                contentid="content%s_%s" % (self.book_id, title[0])     
                no+=1
                even_class_flag=('',' class="even"')[(no-3)%2] # for css
                
                render_for['itemlist'].append(render_for['itemlist'][0] % {'contentid':contentid})
                render_for['itemreflist'].append(render_for['itemreflist'][0] % {'contentid':contentid})
                render_for['navPointlist'].append(render_for['navPointlist'][0] % {'contentid':contentid, 'title':title[1], 'no':str(no)})
                render_for['titlelist'].append(render_for['titlelist'][0] % {'contentid':contentid, 'title':title[1], 'even_class_flag':even_class_flag})
                
            del title_all
            
            # add page site.
            no+=1
            even_class_flag=('',' class="even"')[(no-3)%2]
            render_for['titlelist'].append(render_for['titlelist'][0].replace('html','xhtml') % {'contentid':'page', 'title':'关于%s' % book_info['sitenameabbr'], 'even_class_flag':even_class_flag})
            render_for['navPointlist'].append(render_for['navPointlist'][0].replace('html','xhtml') % {'contentid':'page', 'title':'关于%s' % book_info['sitenameabbr'], 'no':str(no)})
            
            def render(f_str):
                if '%' in f_str:
                    f_str=f_str.replace('%','%%')
                f_str=sub('(\{\{[a-z]{1,20}\}\})',lambda x:"".join(['%','(',x.group(1)[2:-2],')','s']) , f_str, U)
                f_str=f_str % book_info
                if '%%' in f_str:
                    f_str=f_str.replace('%%','%')
                return f_str
            
            # catalog.html, toc.ncx, content.opf, title.xhtml
            with file('catalog.html','r+') as cat_t, file('toc.ncx','r+') as toc_t, \
                file('content.opf','r+') as con_t, file('title.xhtml','r+') as tit_t :
                
                tit_str=tit_t.read()
                tit_str=tit_str.replace('\r',"")
                tit_t.seek(0)
                tit_t.write(render(tit_str))
                del tit_str
                
                cat_str=cat_t.read()
                cat_str=cat_str.replace('\r',"")
                cat_t.seek(0)
                
                toc_str=toc_t.read()
                toc_t.seek(0)
                
                con_str=con_t.read()
                con_t.seek(0)
                
                cat_str=cat_str.replace('{{for_titlelist}}',"\n".join(render_for['titlelist'][1:]))
                cat_t.write(render(cat_str))
                del cat_str
                toc_str=toc_str.replace('{{for_navPointlist}}',"".join(render_for['navPointlist'][1:]))
                toc_t.write(render(toc_str))
                del toc_str
                con_str=con_str.replace('{{for_itemlist}}',"".join(render_for['itemlist'][1:]))
                con_str=con_str.replace('{{for_itemreflist}}',"".join(render_for['itemreflist'][1:]))
                con_t.write(render(con_str))
                del con_str
                
            del render_for
            
            # get cover.jpg 
            jpg=file('cover.jpg','wb')
            jpg.write(self.open_url(book_info['img_url']))
            jpg.close()
            
            print '===Being generated.'
            # zip *.epub
            zip=ZipFile(epub_path,'w',ZIP_DEFLATED)
            for b,ds,fs in walk('.'):
                for ff in fs:
                    zip.write(join(b,ff))
            zip.close()
            
            print "===Cleaned temp files."
            chdir("../.") 
            rmtree(self.book_id)
            sleep(3)
            
            print '===Finish!'
            print "Epub file path is ./%s.epub." % self.win_encode(self.book_name)
            
        except Exception as e:
            with file('log','w') as log:
                log.write(str(resume))
            
            print "Fail!"
            print "Test whether you can read this novel on <biqugecom.com> with your browser. If it's okay, you can re-run program again or feedback this issue to < https://github.com/hipro/BiqugeEpub >."
        #finally:
        #    return None

def main():   
    epub=BiqugeEpub(argv[1])
    epub.generate_epub()

# def test():
#     epub=BiqugeEpub("凡人修仙传")#create a BiqugeEpub class
#     #print epub.query_book_info()
#     epub.generate_epub()
# test()

if __name__ == '__main__':
    if len(argv)<2:
        info='''Input args error, please type: "%(script)s Book_Name_You_Want".'''
        esc(info % { 'script':argv[0] })
    else:
        main()