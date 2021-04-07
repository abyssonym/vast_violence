from randomtools.tablereader import (
    TableObject, addresses, get_activated_patches, get_open_file,
    mutate_normal)
from randomtools.utils import (
    classproperty, cached_property, utilrandom as random)
from randomtools.interface import (
    run_interface, clean_and_write, finish_interface,
    get_activated_codes)
from collections import Counter
from math import ceil
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


class AcquireItemMixin(TableObject):
    flag = 't'

    @classmethod
    def get_item_by_type_index(self, item_type, item_index):
        if item_type in ItemMixin.ITEM_TYPE_MAP:
            obj = ItemMixin.ITEM_TYPE_MAP[item_type]
            return obj.get(item_index)
        return None

    @property
    def item(self):
        return self.get_item_by_type_index(self.item_type, self.item_index)

    @property
    def old_item(self):
        return self.get_item_by_type_index(self.old_data['item_type'],
                                           self.old_data['item_index'])

    @property
    def name(self):
        item = self.item
        if item is None:
            return 'NONE'
        return item.name

    def mutate(self):
        item = self.item
        if item is None:
            candidates = [i for i in ItemMixin.ranked_shuffle_items
                          if 0 <= i.old_data['price'] <= self.value]
            item = candidates[-1]
        new_item = item.get_similar(random_degree=self.random_degree)
        self.item_index = new_item.index
        self.item_type = ItemMixin.item_type_from_item(new_item)


class ItemMixin(NameMixin):
    flag = 's'
    mutate_attributes = {'price': (1, 65000)}

    @classproperty
    def ITEM_TYPE_MAP(self):
        return {
            0: ItemObject,
            1: WeaponObject,
            2: ArmorObject,
            3: AccessoryObject,
            4: KeyItemObject,
            }

    @classmethod
    def item_type_from_item(self, item):
        for k in sorted(ItemMixin.ITEM_TYPE_MAP):
            if isinstance(item, ItemMixin.ITEM_TYPE_MAP[k]):
                return k

    @classproperty
    def shuffle_items(self):
        if hasattr(self, '_shuffle_items'):
            return self._shuffle_items

        shuffle_items = (
            ItemObject.every +
            WeaponObject.every +
            ArmorObject.every +
            AccessoryObject.every
            )
        shuffle_items = [i for i in shuffle_items if i.index > 0
                         and i.intershuffle_valid]
        self._shuffle_items = shuffle_items

        return self.shuffle_items

    @classproperty
    def ranked_shuffle_items(self):
        if hasattr(self, '_ranked_shuffle_items'):
            return self._ranked_shuffle_items

        self._ranked_shuffle_items = sorted(
            self.shuffle_items, key=lambda i: (i.rank, i.signature, i.name))
        return self.ranked_shuffle_items

    @property
    def rank(self):
        if hasattr(self, '_rank'):
            return self._rank

        sorted_items = sorted(
            self.shuffle_items, key=lambda i: (
                i.old_data['price'], i.signature, i.name))

        max_index = len(sorted_items)-1
        for (n, i) in enumerate(sorted_items):
            i._global_rank = n / max_index

        for obj_class in [ItemObject, WeaponObject,
                          ArmorObject, AccessoryObject]:
            for i in obj_class.every:
                i._rank = -1

            sorted_local = [i for i in sorted_items
                            if isinstance(i, obj_class)]
            max_index = len(sorted_local)-1
            for (n, i) in enumerate(sorted_local):
                i._local_rank = n / max_index

        for i in sorted_items:
            i._rank = (i._local_rank + i._global_rank) / 2

        sorted_items = sorted(
            self.shuffle_items, key=lambda i: (i._rank, i.signature, i.name))

        max_index = len(sorted_items)-1
        for n, i in enumerate(sorted_items):
            i._rank = n / max_index

        return self.rank

    def get_similar(self, candidates=None, override_outsider=False,
                    random_degree=None):
        if candidates is None:
            candidates = ItemMixin.ranked_shuffle_items
        new_item = super().get_similar(candidates=candidates,
                                       override_outsider=override_outsider,
                                       random_degree=random_degree)
        return new_item

    def cleanup(self):
        if self.price >= 100:
            self.price = int(float('%.2g' % (self.price*2)) / 2)
        else:
            self.price = int(float('%.1g' % (self.price*2)) / 2)


class DupeMixin:
    @property
    def fingerprint(self):
        return str(sorted(self.old_data.items()))

    def cleanup(self):
        if hasattr(self, 'memory') and self.memory == 0xff:
            return
        for o in sorted(self.every, key=lambda oo: oo.index):
            if o.index >= self.index:
                break
            if o.fingerprint == self.fingerprint:
                for attr in self.old_data:
                    setattr(self, attr, getattr(o, attr))


class FairyGiftObject(AcquireItemMixin): pass
class FairyExploreObject(AcquireItemMixin): pass
class FairyObject(NameMixin): pass
class FairyPrizeObject(AcquireItemMixin): pass


class ItemObject(ItemMixin):
    @property
    def intershuffle_valid(self):
        WHITELIST = []
        return self.index < 0x4e or self.index in WHITELIST


class KeyItemObject(NameMixin): pass
class WeaponObject(ItemMixin): pass
class ArmorObject(ItemMixin): pass
class AccessoryObject(ItemMixin): pass
class AbilityObject(NameMixin): pass
class LevelObject(TableObject): pass

class ShopObject(TableObject):
    flag = 's'
    flag_description = 'shops and trades'

    def __repr__(self):
        s = 'SHOP {0:0>2X} {1:0>2X}\n'.format(self.index, self.unknown)
        for item in self.items:
            if item.name != 'Nothing':
                s += '  {0:12} {1:>5}\n'.format(item.name, item.price)
        return s.strip()

    @property
    def comparison(self):
        if self.items == self.old_items:
            return self.__repr__()

        s = 'SHOP {0:0>2X} {1:0>2X}\n'.format(self.index, self.unknown)
        for old_item, new_item in zip(self.old_items, self.items):
            s += '  {0:12} {1:>5} -> {2:12} {3:>5}\n'.format(
                old_item.name, old_item.price, new_item.name, new_item.price)
        return s.strip()

    @property
    def item_types(self):
        return [v & 0xff for v in self.item_type_item_indexes]

    @property
    def item_indexes(self):
        return [v >> 8 for v in self.item_type_item_indexes]

    @classmethod
    def items_from_indexes(self, item_types, item_indexes):
        items = []
        for item_type, item_index in zip(item_types, item_indexes):
            obj = ItemMixin.ITEM_TYPE_MAP[item_type]
            item = obj.get(item_index)
            items.append(item)
        return items

    @property
    def items(self):
        return self.items_from_indexes(self.item_types, self.item_indexes)

    @property
    def old_items(self):
        item_types = [v & 0xff for v in
                      self.old_data['item_type_item_indexes']]
        item_indexes = [v >> 8 for v in
                        self.old_data['item_type_item_indexes']]
        return self.items_from_indexes(item_types, item_indexes)

    def item_type_from_item(self, item):
        return ItemMixin.item_type_from_item(item)

    def set_items(self, items):
        self.item_type_item_indexes = [
            (i.index << 8) | self.item_type_from_item(i) for i in items]
        assert self.items == items

    def mutate(self):
        random_degree = self.random_degree ** 0.5
        candidates = []

        valid_items = [i for i in self.old_items if i.index > 0]
        for s in ShopObject.every:
            shop_items = [i for i in s.old_items if i.index > 0]
            for i in valid_items:
                if i in shop_items:
                    candidates += shop_items
        candidates = sorted(candidates, key=lambda i: i.rank)

        duplicates_allowed = len(set(valid_items)) != len(valid_items)
        new_items = []
        for i in self.old_items:
            if i.index == 0:
                continue

            if (not isinstance(i, ItemObject) and
                    random.random() < random_degree):
                my_candidates = [c for c in ItemMixin.ranked_shuffle_items
                                 if type(c) == type(i)]
            else:
                my_candidates = list(candidates)

            if not duplicates_allowed:
                my_candidates = [c for c in my_candidates
                                 if c is i or c not in new_items]
            while my_candidates.count(i) > 1:
                my_candidates.remove(i)

            index = my_candidates.index(i)
            if i in new_items:
                my_candidates.remove(i)
            if my_candidates:
                max_index = len(my_candidates)-1
                index = min(max(index, 0), max_index)
                index = mutate_normal(index, 0, max_index,
                                      random_degree=random_degree)
                new_item = my_candidates[index]
            else:
                new_item = i
            new_items.append(new_item)

        self.set_items(new_items)

    def cleanup(self):
        sorted_items = sorted(
            self.items, key=lambda i: (
                self.item_type_from_item(i),
                i.equip_type if isinstance(i, ArmorObject) else 0,
                i.name))
        sorted_items = [i for i in sorted_items if i.index > 0]
        if not 0x11 <= self.index <= 0x16:  # faerie shops
            self.set_items(sorted_items)

        while len(self.items) < len(self.old_data['item_type_item_indexes']):
            self.item_type_item_indexes.append(0)


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


class ChestObject(DupeMixin, AcquireItemMixin):
    flag_description = 'treasure'

    def __repr__(self):
        if self.item:
            s = 'CHEST {0:0>2X} ({1:0>3}-{2:0>2x}): {3}'.format(
                self.index, self.area_code, self.memory, self.item.name)
        else:
            assert self.item_type == 0xFF
            zenny = '{0}Z'.format(self.value)
            s = 'CHEST {0:0>2X} ({1:0>3}-{2:0>2x}): {3}'.format(
                self.index, self.area_code, self.memory, zenny)
        return s

    @property
    def value(self):
        if self.item:
            return self.item.old_data['price']
        assert self.item_type == 0xFF
        return self.item_index * 40

    @property
    def area_code(self):
        filename = self.filename[-11:]
        assert filename.startswith('AREA') and filename.endswith('.EMI')
        return int(filename[-7:-4])


class GeneObject(TableObject):
    flag = 'g'
    flag_description = 'dragon gene locations'
    intershuffle_attributes = ['gene_index']

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


class ManilloItemObject(DupeMixin, AcquireItemMixin):
    flag = 's'

    def __repr__(self):
        fishdesc = ', '.join(
            '{0} x{1}'.format(fish.name, n) for (fish, n) in self.fishes)
        s = 'TRADE {0:0>2X}: {1} ({2})'.format(
            self.index, self.item.name, fishdesc)
        return s.strip()

    @property
    def fishes(self):
        fishes = []
        for i, n in zip(self.fish_indexes, self.fish_quantities):
            if i == 0xFF or n == 0:
                continue
            fish = ItemObject.get(0x38 + i)
            fishes.append((fish, n))
        return fishes

    def mutate(self):
        super().mutate()
        if self.random_degree == 0:
            return

        old_fish_value = 0
        for (fish, n) in self.fishes:
            old_fish_value += (fish.old_data['price'] * n)

        values = [self.old_item.old_data['price'],
                  self.old_item.price,
                  self.item.old_data['price'],
                  self.item.price]

        old_item_value = self.old_item.old_data['price']
        target_value = random.randint(min(values), max(values))
        target_fish_value = target_value * old_fish_value / old_item_value
        new_fishes = [(None, 0), (None, 0), (None, 0)]
        candidate_fishes = sorted(
            [ItemObject.get(i) for i in range(0x38, 0x4d)],
            key=lambda i: i.old_data['price'])
        target_fish_value = max(
            target_fish_value, min([f.old_data['price']
                                    for f in candidate_fishes]))
        max_index = len(candidate_fishes)-1
        while True:
            index = int(round(
                (random.random() ** (1/self.random_degree)) * max_index))
            replacement_fish = candidate_fishes[index]
            if replacement_fish.old_data['price'] > target_fish_value * 2:
                continue
            for (fish, n) in new_fishes:
                if fish == replacement_fish:
                    replace_fish = fish
                    replace_quantity = n
                    replacement_quantity = n + 1
                    break
            else:
                replace_fish, replace_quantity = random.choice(new_fishes)
                if replace_fish is not None:
                    replace_value = (replace_fish.old_data['price']
                                     * replace_quantity)
                    replacement_quantity = ceil(
                        replace_value / replacement_fish.old_data['price'])
                else:
                    replacement_quantity = random.randint(
                        1, random.randint(1, 9))

            if 1 <= replacement_quantity <= 9:
                new_fishes.remove((replace_fish, replace_quantity))
                new_fishes.append((replacement_fish, replacement_quantity))
            else:
                continue

            current_value = 0
            for (fish, n) in new_fishes:
                if fish is None:
                    continue
                current_value += (fish.old_data['price'] * n)
            if current_value >= target_fish_value:
                break

        self.fish_indexes = [fish.index-0x38 if fish else 0xFF
                             for fish, n in new_fishes]
        self.fish_quantities = [n if fish else 0 for fish, n in new_fishes]


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
