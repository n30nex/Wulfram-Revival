"""Entity lifecycle must not invalidate a snapshot or discard a new spawn."""
import concurrent.futures
import unittest
from types import SimpleNamespace
from test_bots import make_server
from wulfram_server import application as app
from wulfram_server.core.entity import UpdateMask
from wulfram_server.core.entity_manager import EntityManager


class EntityConcurrencyTests(unittest.TestCase):
    def test_registry_mutation_during_dirty_iteration_uses_stable_membership(self):
        manager=EntityManager()
        class MutatingEntity:
            net_id=100
            @property
            def pending_mask(self):
                manager.create_entity(0,1)
                return 1
        original=MutatingEntity()
        manager.register_entity(original)
        self.assertEqual(manager.get_dirty_entities(),[original])
        self.assertEqual(len(manager.get_all()),2)

    def test_new_spawn_and_changed_state_survive_an_inflight_broadcast(self):
        server=make_server()
        owner=server.entities.create_entity(0,1)
        other=server.entities.create_entity(0,2)
        created=[]
        def send(_):
            if not created:
                created.append(server.entities.create_entity(0,2))
                other.mark_dirty(UpdateMask.WEAPON)
        session=SimpleNamespace(is_logged_in=True,is_ready_for_updates=True,entity=owner,
                                udp_context=SimpleNamespace(send=send),team=1,player_id=1)
        server.sessions=[session]
        server._last_hard_sync_log=0
        app._broadcast_dirty_state(server,send_view_updates=False)
        self.assertTrue(created[0].pending_mask & UpdateMask.DEFINITION)
        self.assertTrue(other.pending_mask & UpdateMask.WEAPON)
        self.assertTrue(other.pending_view_mask & UpdateMask.WEAPON)

    def test_parallel_entity_ids_are_unique_and_snapshots_remain_iterable(self):
        manager=EntityManager()
        def mutate(_):
            ids=[]
            for _ in range(300):
                entity=manager.create_entity(0,1)
                ids.append(entity.net_id)
                manager.get_dirty_entities()
                manager.get_view_dirty_entities()
                manager.remove_entity(entity.net_id)
            return ids
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=[value for batch in pool.map(mutate,range(8)) for value in batch]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(manager.get_all(),[])


if __name__=='__main__': unittest.main()
