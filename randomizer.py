from randomtools.tablereader import (
    TableObject, addresses, get_activated_patches, get_open_file)
from randomtools.utils import (
    classproperty, cached_property, utilrandom as random)
from randomtools.interface import (
    run_interface, clean_and_write, finish_interface,
    get_activated_codes)
from collections import Counter
from sys import argv
from traceback import format_exc


VERSION = 1
ALL_OBJECTS = None


class NameMixin(TableObject):
    CHARSWAPS = {
        b'\xff': b'\x20',
        b'\x8e': b'\x27',
        }

    @property
    def name(self):
        for attr in self.old_data:
            if attr.endswith('_name'):
                name = getattr(self, attr)
                break
        for c in self.CHARSWAPS:
            name = name.replace(c, self.CHARSWAPS[c])
        return name.decode('ascii').rstrip('\x00')


class ItemObject(NameMixin): pass
class KeyItemObject(NameMixin): pass
class WeaponObject(NameMixin): pass
class ArmorObject(NameMixin): pass
class AccessoryObject(NameMixin): pass
class AbilityObject(NameMixin): pass
class LevelObject(TableObject): pass

class ShopObject(TableObject):
    ITEM_TYPE_MAP = {
        0: ItemObject,
        1: WeaponObject,
        2: ArmorObject,
        3: AccessoryObject,
        4: KeyItemObject,
        }

    def __repr__(self):
        s = 'SHOP {0:0>2X} {1:0>2X}\n'.format(self.index, self.unknown)
        for item in self.items:
            if item.name != 'Nothing':
                s += '  {0:12} {1:>5}\n'.format(item.name, item.price)
        return s.strip()

    @property
    def item_types(self):
        return [v & 0xff for v in self.item_type_item_indexes]

    @property
    def item_indexes(self):
        return [v >> 8 for v in self.item_type_item_indexes]

    @property
    def items(self):
        items = []
        for item_type, item_index in zip(self.item_types, self.item_indexes):
            obj = self.ITEM_TYPE_MAP[item_type]
            item = obj.get(item_index)
            items.append(item)
        return items

class MasterSkillObject(TableObject): pass
class MasterStatsObject(TableObject): pass
class BaseStatsObject(NameMixin):
    def cleanup(self):
        if 'easymodo' in get_activated_codes():
            self.accuracy = 100
            self.base_accuracy = 100
            self.current_hp = 999
            self.max_hp = 999
            self.base_max_hp = 999


class ChestObject(TableObject):
    def __repr__(self):
        if self.item:
            s = 'CHEST {0:0>2X} ({1:0>3}-{2:0>2x}): {3}'.format(
                self.index, self.area_code, self.memory, self.item.name)
        else:
            assert self.item_type == 0xFF
            zenny = '{0}Z'.format(self.item_index * 40)
            s = 'CHEST {0:0>2X} ({1:0>3}-{2:0>2x}): {3}'.format(
                self.index, self.area_code, self.memory, zenny)
        return s

    @property
    def area_code(self):
        filename = self.filename[-11:]
        assert filename.startswith('AREA') and filename.endswith('.EMI')
        return int(filename[-7:-4])

    @property
    def item(self):
        if self.item_type in ShopObject.ITEM_TYPE_MAP:
            obj = ShopObject.ITEM_TYPE_MAP[self.item_type]
            return obj.get(self.item_index)
        return None


class GeneObject(TableObject):
    def cleanup(self):
        if self.gene_index == 0x21:
            assert 'patch_flame_gene.txt' in get_activated_patches()
            self.gene_index = 0
        assert 0 <= self.gene_index <= 0x11


class FormationObject(TableObject):
    def __repr__(self):
        s = 'FORMATION {0:0>3X} ({1}): '.format(
            self.index, self.appearance_rate)
        counts = dict(Counter(self.enemies))
        if None in counts:
            del(counts[None])
        if not counts:
            s += 'Nothing'
            return s.strip()
        monster_counts = sorted(counts.items(),
                               key=lambda item: (counts[item[0]], item[0].name))
        s += ', '.join(['{0} x{1} '.format(monster.name, count)
                        for monster, count in monster_counts])
        return s.strip()

    @cached_property
    def available_enemies(self):
        return [e for e in MonsterObject.every if e.filename == self.filename]

    @property
    def enemies(self):
        return [self.available_enemies[eid] if eid < 0xff else None
                for eid in self.monster_indexes]

    def cleanup(self):
        if 'easymodo' in get_activated_codes():
            self.appearance_rate = 0
            if self.old_data['appearance_rate'] != 0:
                self.monster_indexes = [0xff]*8


class ManilloItemObject(TableObject):
    def __repr__(self):
        fishdesc = ', '.join(
            '{0} x{1}'.format(fish.name, n) for (fish, n) in self.fishes)
        s = 'TRADE {0:0>2X}: {1} ({2})'.format(
            self.index, self.item.name, fishdesc)
        return s.strip()

    @property
    def item(self):
        obj = ShopObject.ITEM_TYPE_MAP[self.item_type]
        return obj.get(self.item_index)

    @property
    def fishes(self):
        fishes = []
        for i, n in zip(self.fish_indexes, self.fish_quantities):
            if i == 0xFF or n == 0:
                continue
            fish = ItemObject.get(0x38 + i)
            fishes.append((fish, n))
        return fishes


class MonsterObject(NameMixin):
    def cleanup(self):
        if 'easymodo' in get_activated_codes():
            self.hp = min(self.old_data['hp'], 1)


if __name__ == '__main__':
    try:
        print ('You are using the Breath of Fire III '
               'randomizer version %s.' % VERSION)

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]
        codes = {
            'easymodo': ['easymodo'],
            }
        run_interface(ALL_OBJECTS, snes=False, codes=codes,
                      custom_degree=True)

        clean_and_write(ALL_OBJECTS)
        finish_interface()

    except Exception:
        print(format_exc())
        input('Press Enter to close this program. ')
