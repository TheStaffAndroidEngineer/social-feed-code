"""Independent Fieldnotes protocol checks; execute in an isolated Python process."""
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from base import Problem, handler
from service import Service


class FieldnotesReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fieldnotes-review-')
        self.addCleanup(self.temp.cleanup)
        self.database=Path(self.temp.name)/'feed.sqlite'
        self.time=[1_000_000]
        self.a=Service(self.database,clock=lambda:self.time[0])
        self.b=Service(self.database,clock=lambda:self.time[0])
        self.servers=[];self.addCleanup(self.stop)

    def stop(self):
        for server,thread in self.servers:
            server.shutdown();server.server_close();thread.join(2)

    def serve(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.a))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start();self.servers.append((server,thread))
        return f'http://127.0.0.1:{server.server_port}'

    def envelope(self,action,args,identity=None):
        return {'id':identity or str(uuid.uuid4()),'action':action,'args':args}

    def command(self,action,args,identity=None,owner=None):
        return (owner or self.a).route('POST','/commands',self.envelope(action,args,identity))[1]

    def opened(self,topic='All'):
        outcome=self.command('open',{'topic':topic})['outcome']
        self.assertTrue(outcome['accepted']);return outcome['sessionId']

    def page(self,session,offset=0,topic='All',owner=None):
        return (owner or self.a).route('GET',f'/feed/{session}?'+urlencode({'offset':offset,'topic':topic}),{})[1]['data']

    def all_pages(self,session,topic='All'):
        offset=0;items=[];positions=[]
        while True:
            page=self.page(session,offset,topic)
            self.assertEqual(offset+page['consumedPositions'],page['nextOffset'])
            self.assertLessEqual(len(page['items']),page['consumedPositions'])
            items.extend(page['items']);positions.append(page['nextOffset'])
            if not page['more']:return items,positions
            self.assertGreater(page['nextOffset'],offset);offset=page['nextOffset']

    def http(self,base,path,body=None):
        req=Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=4) as response:return response.status,json.load(response)

    def publish(self,post_id,score=1000,topic='Places',owner=None):
        return self.command('publish',{'postId':post_id,'title':'New original story','topic':topic,'score':score},owner=owner)

    def test_new_ranked_head_cannot_shift_an_existing_snapshot_cursor(self):
        old=self.opened();first=self.page(old)
        self.publish('new-head')
        second=self.page(old,first['nextOffset'])
        self.assertEqual(['post-04','post-05','post-06'],[p['id'] for p in second['items']])
        old_items,positions=self.all_pages(old)
        self.assertEqual([3,6,9,12],positions)
        self.assertEqual(12,len({p['id'] for p in old_items}))
        self.assertNotIn('new-head',[p['id'] for p in old_items])
        self.assertEqual('new-head',self.page(self.opened())['items'][0]['id'])
        self.assertEqual(first['snapshotRevision'],second['snapshotRevision'])

    def test_equal_scores_have_stable_id_tie_break_independent_of_publication_order(self):
        self.publish('tie-z',900);self.publish('tie-a',900)
        self.assertEqual(['tie-a','tie-z'],[p['id'] for p in self.page(self.opened())['items'][:2]])

    def test_hidden_entire_page_still_consumes_positions_and_advances(self):
        session=self.opened()
        for i in range(1,4):self.command('hide',{'postId':f'post-{i:02}'})
        empty=self.page(session)
        self.assertEqual([],empty['items']);self.assertTrue(empty['more'])
        self.assertEqual((3,3),(empty['nextOffset'],empty['consumedPositions']))
        self.assertEqual(['post-04','post-05','post-06'],[p['id'] for p in self.page(session,3)['items']])

    def test_visibility_refresh_removes_old_rows_without_changing_snapshot_order(self):
        session=self.opened();initial=self.page(session)
        self.assertEqual('post-02',initial['items'][1]['id'])
        self.command('hide',{'postId':'post-02'})
        current=self.page(session)
        self.assertEqual(['post-01','post-03'],[p['id'] for p in current['items']])
        self.assertEqual(3,current['nextOffset'])
        for i in range(1,13):self.command('hide',{'postId':f'post-{i:02}'})
        rows,positions=self.all_pages(session)
        self.assertEqual([],rows);self.assertEqual([3,6,9,12],positions)
        new=self.page(self.opened())
        self.assertEqual(([],0,False),(new['items'],new['nextOffset'],new['more']))

    def test_expiry_exact_boundary_and_historical_open_replay_do_not_renew_session(self):
        command=self.envelope('open',{'topic':'All'})
        receipt=self.a.route('POST','/commands',command)[1]
        session=receipt['outcome']['sessionId'];expiry=self.page(session)['expiresAt']
        self.time[0]=expiry-1;self.page(session)
        self.time[0]=expiry
        with self.assertRaises(Problem) as error:self.page(session)
        self.assertEqual(410,error.exception.status)
        reopened=Service(self.database,clock=lambda:self.time[0])
        self.assertEqual(receipt,reopened.route('POST','/commands',command)[1])
        with self.assertRaises(Problem) as error:self.page(session,owner=reopened)
        self.assertEqual(410,error.exception.status)

    def test_topic_is_bound_to_cursor_and_filtered_order(self):
        session=self.opened('Making')
        rows,positions=self.all_pages(session,'Making')
        self.assertEqual(['post-02','post-05','post-08','post-11'],[p['id'] for p in rows])
        self.assertEqual([3,4],positions)
        with self.assertRaises(Problem) as error:self.page(session,topic='Places')
        self.assertEqual(409,error.exception.status)
        with self.assertRaises(Problem) as error:self.page(str(uuid.uuid4()))
        self.assertEqual(404,error.exception.status)

    def test_lost_open_reply_recovers_exactly_one_persisted_session(self):
        base=self.serve();command=self.envelope('open',{'topic':'People'})
        self.http(base,'/__control',{'drop_reply':True})
        with self.assertRaises(OSError):self.http(base,'/commands',command)
        self.http(base,'/__control',{})
        reopened=Service(self.database,clock=lambda:self.time[0])
        receipt=reopened.route('POST','/commands',command)[1]
        state=reopened.route('GET','/__control',{})[1]['state']
        self.assertEqual([receipt['outcome']['sessionId']],list(state['sessions']))
        self.assertEqual('People',self.page(receipt['outcome']['sessionId'],topic='People',owner=reopened)['topic'])

    def test_lost_like_reply_and_new_target_command_never_toggle_back(self):
        session=self.opened();base=self.serve()
        command=self.envelope('like',{'postId':'post-01','liked':True})
        self.http(base,'/__control',{'drop_reply':True})
        with self.assertRaises(OSError):self.http(base,'/commands',command)
        self.http(base,'/__control',{})
        reopened=Service(self.database,clock=lambda:self.time[0])
        reopened.route('POST','/commands',command)
        self.assertTrue(self.page(session,owner=reopened)['items'][0]['liked'])
        self.command('like',{'postId':'post-01','liked':True},owner=reopened)
        self.assertTrue(self.page(session)['items'][0]['liked'])
        with self.assertRaises(Problem):self.command('like',{'postId':'post-01','liked':False},command['id'])
        self.command('like',{'postId':'post-01','liked':False})
        self.assertFalse(self.page(session)['items'][0]['liked'])

    def test_hidden_like_refusal_and_conflicting_publish_identity_stay_negative(self):
        self.command('hide',{'postId':'post-01'})
        command=self.envelope('like',{'postId':'post-01','liked':True})
        refusal=self.a.route('POST','/commands',command)[1]
        self.assertFalse(refusal['outcome']['accepted'])
        reopened=Service(self.database,clock=lambda:self.time[0])
        self.assertEqual(refusal,reopened.route('POST','/commands',command)[1])
        self.assertFalse(self.publish('post-01')['outcome']['accepted'])

    def test_two_service_owners_cannot_publish_two_posts_under_one_identity(self):
        barrier=threading.Barrier(2)
        def run(owner):barrier.wait();return self.publish('shared',owner=owner)['outcome']
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(run,(self.a,self.b)))
        self.assertEqual(1,sum(r['accepted'] for r in results))
        rows,_=self.all_pages(self.opened())
        self.assertEqual(1,sum(p['id']=='shared' for p in rows))

    def test_expired_snapshot_limit_is_explicit_and_old_ids_remain_recognizable(self):
        first=self.opened()
        for _ in range(99):self.opened()
        self.time[0]+=120000
        self.assertFalse(self.command('open',{'topic':'All'})['outcome']['accepted'])
        with self.assertRaises(Problem) as error:self.page(first)
        self.assertEqual(410,error.exception.status)

    def test_bad_offset_queries_and_boolean_score_cannot_change_content(self):
        session=self.opened();base=self.serve()
        for query in ('offset=-1&topic=All','offset=13&topic=All','offset=1.0&topic=All',
                      'offset=0&offset=3&topic=All','offset=0&topic=All&extra=1','offset=%C2%B2&topic=All'):
            with self.subTest(query=query):
                with self.assertRaises(HTTPError) as error:self.http(base,f'/feed/{session}?{query}')
                self.assertEqual(400,error.exception.code)
        with self.assertRaises(Problem):self.publish('invalid',True)
        rows,_=self.all_pages(session);self.assertEqual(12,len(rows))


    def test_observed_expiry_remains_terminal_after_clock_rollback_and_reconstruction(self):
        session=self.opened()
        self.time[0]+=120000
        with self.assertRaises(Problem) as expired:self.page(session)
        self.assertEqual(410,expired.exception.status)
        self.time[0]-=120000
        restored=Service(self.database,clock=lambda:self.time[0])
        with self.assertRaises(Problem) as still_expired:self.page(session,owner=restored)
        self.assertEqual(410,still_expired.exception.status)
        fresh=self.opened();self.assertNotEqual(session,fresh)
        self.assertTrue(self.page(fresh)['items'])

if __name__=='__main__':unittest.main()
