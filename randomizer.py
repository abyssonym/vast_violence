from randomtools.tablereader import (
    TableObject, addresses, get_activated_patches, get_open_file,
    mutate_normal, get_seed, get_global_label, tblpath,
    get_random_degree, get_difficulty, write_patch)
from randomtools.utils import (
    classproperty, cached_property, utilrandom as random)
from randomtools.interface import (
    run_interface, clean_and_write, finish_interface,
    get_activated_codes, get_flags, get_outfile)
from collections import Counter, defaultdict
from math import ceil
from os import path
from sys import argv
from traceback import format_exc


VERSION = '3.2'
ALL_OBJECTS = None


class NameMixin(TableObject):
    CHARSWAPS = {
        b'\xff': b'\x20',
        b'\x8b': b'+',
        b'\x3d': b'-',
        b'\x8e': b'\x27',
        b'\x06': b'$NOCOLOR$',
        b'\x01': b'\n',
        b'\x05\x03': b'$BLUE$',
        b'\x05\x02': b'$RED$',
        b'>': b'.',
        }

    @classmethod
    def convert_to_str(self, s):
        for c in self.CHARSWAPS:
            s = s.replace(c, self.CHARSWAPS[c])
        return s.decode('ascii').rstrip('\x00')

    @classmethod
    def convert_from_str(self, s):
        old_s = s
        s = s.encode('ascii')
        inverse_swaps = {}
        for (a, b) in self.CHARSWAPS.items():
            assert b not in inverse_swaps
            inverse_swaps[b] = a
        for c in inverse_swaps:
            s = s.replace(c, inverse_swaps[c])
        assert old_s == self.convert_to_str(s)
        return s

    def set_name(self, name):
        self.old_name
        name = self.convert_from_str(name)
        attr = self._name_attr
        length = [l for (a, l, _) in self.specsattrs if a == attr][0]
        if len(name) > length:
            print('WARNING: Name %s too long. Truncating.' % name)
            name = name[:length]
        while len(name) < length:
            name += b'\xff'
        setattr(self, attr, name)
        assert len(getattr(self, attr)) == len(self.old_data[attr])

    @property
    def name(self):
        old_name = self.old_name
        if getattr(self, self._name_attr) == self.old_data[self._name_attr]:
            return old_name
        else:
            name = getattr(self, self._name_attr)
        return self.convert_to_str(name)

    @cached_property
    def old_name(self):
        for attr in self.old_data:
            if attr.endswith('_name'):
                self._name_attr = attr
                name = self.old_data[attr]
                break
        return self.convert_to_str(name)


class AcquireItemMixin(TableObject):
    flag = 't'
    custom_random_enable = 't'

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

    def mutate(self, unique=False):
        item = self.item

        if not hasattr(self.__class__, '_DONE_ITEMS'):
            self.__class__._DONE_ITEMS = set()

        for _ in range(100):
            if item is None:
                candidates = [i for i in ItemMixin.ranked_shuffle_items
                              if 0 <= i.old_data['price'] <= self.value]
                item = candidates[-1]

            if item.rank < 0 or not item.intershuffle_valid:
                new_item = item
                break

            new_item = item.get_similar(random_degree=self.random_degree)
            if unique and new_item in self.__class__._DONE_ITEMS:
                continue
            self.__class__._DONE_ITEMS.add(new_item)
            break

        self.item_index = new_item.index
        self.item_type = ItemMixin.item_type_from_item(new_item)


class ItemMixin(NameMixin):
    flag = 's'
    mutate_attributes = {'price': (1, 65000)}

    @property
    def magic_mutate_bit_attributes(self):
        if (hasattr(self, 'equipability')
                and EquipmentObject.flag in get_flags()
                and not isinstance(self, WeaponObject)):
            return {'equipability': 0x77}
        return {}

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

    def magic_mutate_bits(self):
        return

    def mutate_equipability(self):
        super().magic_mutate_bits(random_degree=EquipmentObject.random_degree)
        names = {'ryu': 0x01,
                 'nina': 0x02,
                 'garr': 0x04,
                 'rei': 0x10,
                 'momo': 0x20,
                 'peco': 0x40}
        sorted_names = sorted(names)
        if not hasattr(type(self), '_equipment_map'):
            if isinstance(self, WeaponObject):
                shuffled_names = list(sorted_names)
                random.shuffle(shuffled_names)
                equipment_map = dict(zip(sorted_names, shuffled_names))
            else:
                equipment_map = {}
                for n in sorted_names:
                    equipment_map[n] = random.choice(sorted_names)
            type(self)._equipment_map = equipment_map

        value = self.equipability
        for n in sorted_names:
            mapped_from = type(self)._equipment_map[n]
            bitmask = names[mapped_from]
            truth = value & bitmask
            self.set_bit(n, truth)
        self.set_bit('teepo', True)

    def preclean(self):
        if hasattr(self, 'equipability') and self.old_data['equipability'] > 0:
            characters = ['ryu', 'nina', 'garr', 'rei', 'momo', 'peco']
            if not any(self.get_bit(c) for c in characters):
                c = random.choice(characters)
                self.set_bit(c, True)

        for attr in ['willpower', 'base_willpower', 'current_willpower']:
            setattr(self, attr, 0)

    def cleanup(self):
        if hasattr(self, 'equipability'):
            if EquipmentObject.flag not in get_flags():
                assert self.equipability == self.old_data['equipability']
            if self.old_data['equipability'] == 0:
                self.equipability = 0
            elif 'equipanything' in get_activated_codes():
                self.equipability = 0xff

        if self.price >= 100:
            self.price = int(float('%.2g' % (self.price*2)) / 2)
        else:
            self.price = int(float('%.1g' % (self.price*2)) / 2)


class DupeMixin:
    @cached_property
    def fingerprint(self):
        return str(sorted(self.old_data.items()))

    @cached_property
    def canonical_relative(self):
        for o in sorted(self.every, key=lambda oo: oo.index):
            if (isinstance(self, MonsterObject) and o is self and
                    self.monster_name != self.old_data['monster_name']):
                continue
            if o.index >= self.index:
                return self
            if o.fingerprint == self.fingerprint:
                assert o.is_canonical
                return o

    @cached_property
    def is_canonical(self):
        return self.canonical_relative is self

    def cleanup(self):
        if hasattr(self, 'memory') and self.memory == 0xff:
            return
        if self.canonical_relative is not self:
            for attr in self.old_data:
                setattr(self, attr, getattr(self.canonical_relative, attr))


class EquipmentObject(TableObject):
    flag = 'q'
    flag_description = 'equippable items'
    custom_random_enable = 'q'

    def mutate(self):
        assert self.index == 0
        for i in ItemMixin.shuffle_items:
            if hasattr(i, 'equipability'):
                i.reseed('equip')
                i.mutate_equipability()


class MonsterAbilityObject(TableObject):
    flag = 'n'
    flag_description = 'enemy abilities'
    custom_random_enable = 'n'

    def mutate(self):
        for m in MonsterObject.every:
            if m.is_boss or not m.is_canonical:
                continue
            m.mutate_skills()


class FairyGiftObject(AcquireItemMixin): pass
class FairyExploreObject(AcquireItemMixin): pass
class FairyPrizeObject(AcquireItemMixin): pass


class FairyObject(DupeMixin, NameMixin):
    flag = 'c'

    def randomize(self):
        new_stats = []
        for i in range(4):
            f = random.choice(FairyObject.every)
            new_stats.append(f.old_data['stats'][i])
        self.stats = new_stats
        assert len(self.stats) == len(self.old_data['stats'])


class ItemObject(ItemMixin):
    @property
    def intershuffle_valid(self):
        WHITELIST = []
        return self.index < 0x4e or self.index in WHITELIST


class KeyItemObject(NameMixin): pass
class WeaponObject(ItemMixin):
    def cleanup(self):
        super().cleanup()
        if 'HE Shells' in self.name:
            self.set_bit('momo', True)


class ArmorObject(ItemMixin): pass
class AccessoryObject(ItemMixin): pass


class AbilityObject(NameMixin):
    flag = 'a'
    flag_description = 'abilities'
    custom_random_enable = 'a'

    HEALING_SKILL = 0
    ASSIST_SKILL = 1
    ATTACK_SKILL = 2
    EXAMINE_SKILL = 3

    BANNED_SKILLS = ['Head Cracker', 'Nue Stomp']
    LEVELUP_BANNED_SKILLS = ['Backhand']

    @property
    def intershuffle_valid(self):
        if self.rank < 0:
            return False
        return (self._levelup_rank is None
                or self.get_bit('examinable'))

    @property
    def is_spare_levelup_skill(self):
        if len([a for a in self.every if a.old_name == self.old_name]) == 1:
            return False
        return not self.intershuffle_valid

    @property
    def is_boss_skill(self):
        if hasattr(self, '_is_boss_skill'):
            return self._is_boss_skill

        for a in AbilityObject.every:
            a._is_boss_skill = False

        for m in MonsterObject.every:
            if m.is_boss:
                for a in m.abilities:
                    a._is_boss_skill = True

        for m in MonsterObject.every:
            if not m.is_boss:
                for a in m.abilities:
                    a._is_boss_skill = False

        return self.is_boss_skill

    @cached_property
    def examine_alt(self):
        if self.name == 'Noting':
            return None
        selves = [a for a in self.every if a.old_name == self.old_name]
        if len(selves) == 1:
            return self
        examinable = [a for a in selves if a.get_bit('examinable')]
        assert len(examinable) <= 1
        if examinable:
            return examinable[0]
        return None

    @cached_property
    def levelup_alt(self):
        if self.name == 'Noting':
            return None
        selves = [a for a in self.every if a.old_name == self.old_name]
        if len(selves) == 1:
            return self
        unexaminable = [a for a in selves if not a.get_bit('examinable')]
        if len(unexaminable) > 1:
            return sorted(unexaminable, key=lambda a: a.index)[0]
        if unexaminable:
            return unexaminable[0]
        return None

    @property
    def is_offense(self):
        return self.get_bit('default_target_enemy')

    @cached_property
    def is_utility(self):
        elements = ['fire', 'ice', 'lightning', 'earth', 'wind', 'holy']
        for e in elements:
            if self.get_bit(e):
                return False
        return self.get_bit('psionic') or self.get_bit('status')

    def calculate_skill_type(self):
        if self.is_utility:
            skill_type = self.ASSIST_SKILL
        elif self.is_offense:
            skill_type = self.ATTACK_SKILL
        else:
            skill_type = self.HEALING_SKILL
        return skill_type

    def reset_skill_type(self, skill_type=None):
        if skill_type is None:
            skill_type = self.calculate_skill_type()

        self.skill_type &= 0xFC
        self.skill_type |= skill_type

    @property
    def rank(self):
        if hasattr(self, '_rank'):
            return self._rank

        for a in AbilityObject.every:
            a._monster_rank = None
            a._levelup_rank = None
            a._master_rank = None

        for m in MonsterObject.ranked:
            if m.rank >= 0:
                for a in m.abilities:
                    a._monster_rank = a._monster_rank or m.rank
                    a._monster_rank = min(a._monster_rank, m.rank)

        max_level = max([l.level for l in LevelObject.every if l.ability > 0])
        for l in LevelObject.every:
            if l.ability > 0:
                a = AbilityObject.get(l.ability)
                a._levelup_rank = a._levelup_rank or l.level / max_level
                a._levelup_rank = min(a._levelup_rank, l.level / max_level)

        for bs in BaseStatsObject.every:
            for a in bs.all_abilities:
                a._levelup_rank = a._levelup_rank or bs.level / max_level
                a._levelup_rank = min(a._levelup_rank, bs.level / max_level)

        max_level = (max([max(ms.levels) for ms in MasterSkillsObject.every])
                     + 1)
        for ms in MasterSkillsObject.every:
            for level, skill in zip(ms.levels, ms.skills):
                skill._master_rank = skill._master_rank or level / max_level
                skill._master_rank = min(skill._master_rank, level / max_level)

        name_ranks = {}
        for a in AbilityObject.every:
            ranks = []
            for attr in ['monster', 'levelup', 'master']:
                rank = getattr(a, '_%s_rank' % attr)
                if rank is not None:
                    ranks.append(rank)

            if a.name and ranks:
                rank_value = sum(ranks) / len(ranks)
                if a.name not in name_ranks:
                    name_ranks[a.name] = set([])
                name_ranks[a.name].add(rank_value)

        for name in ['Nothing', 'Noting']:
            if name in name_ranks:
                del(name_ranks[name])

        for a in AbilityObject.every:
            if a.old_name in AbilityObject.BANNED_SKILLS:
                a._rank = -1
                continue
            if a.name in name_ranks:
                ranks = name_ranks[a.name]
                a._rank = sum(ranks) / len(ranks)
            else:
                a._rank = -1

        return self.rank

    def cleanup(self):
        if self.old_name in self.BANNED_SKILLS:
            self.set_bit('examinable', False)

        if hasattr(self, '_rename'):
            self.set_name(self._rename)


class LevelObject(TableObject):
    def __repr__(self):
        s = '{0:5} {1:0>2}'.format(self.charname, self.level)
        for attr in ['hp', 'ap', 'pwr', 'dfn', 'agi', 'int']:
            value = getattr(self, attr)
            s += ' | {0}: {1}'.format(attr, value)
        return s

    @property
    def level(self):
        return (self.index % 99) + 1

    @property
    def charname(self):
        return BaseStatsObject.get(self.index // 99).name

    def set_stat(self, stat, value):
        for attr in self.old_data:
            old_value = getattr(self, attr)
            if attr == stat:
                setattr(self, attr, value)
            elif attr.startswith(stat):
                old_value &= 0xf
                old_value |= (value << 4)
            elif attr.endswith(stat):
                old_value &= 0xf0
                old_value |= value
                return self.old_data[attr] & 0xf

    def get_old_stat(self, stat):
        for attr in self.old_data:
            if attr == stat:
                return self.old_data[attr]
            elif attr.startswith(stat):
                return self.old_data[attr] >> 4
            elif attr.endswith(stat):
                return self.old_data[attr] & 0xf

    @property
    def pwr(self):
        return self.pwr_dfn >> 4

    @property
    def dfn(self):
        return self.pwr_dfn & 0xf

    @property
    def agi(self):
        return self.agi_int >> 4

    @property
    def int(self):
        return self.agi_int & 0xf


class ShopObject(TableObject):
    flag = 's'
    flag_description = 'shops and trades'
    custom_random_enable = 's'

    def __repr__(self):
        s = 'SHOP {0:0>2X} {1}\n'.format(self.index, self.name)
        for item in self.items:
            if item.name != 'Nothing':
                s += '  {0:12} {1:>5}\n'.format(item.name, item.price)
        return s.strip()

    @property
    def name(self):
        if hasattr(self, '_name'):
            return self._name

        index_names = {}
        with open(path.join(tblpath, 'names_shops.txt')) as f:
            for (i, line) in enumerate(f.readlines()):
                line = line.strip()
                index_names[i] = line

        for s in ShopObject.every:
            s._name = index_names[s.index].upper()

        return self.name

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

    @classproperty
    def item_pools(self):
        if hasattr(ShopObject, '_item_pools'):
            return ShopObject._item_pools

        item_pools = {}
        for i in (ItemObject.every + WeaponObject.every +
                  ArmorObject.every + AccessoryObject.every):
            item_pools[i] = []
            for s in ShopObject.every:
                old_items = [i for i in s.old_items if i.index > 0]
                if i in old_items:
                    item_pools[i] += old_items
        ShopObject._item_pools = item_pools

        return ShopObject.item_pools

    def mutate(self):
        random_degree = self.random_degree ** 0.5

        valid_items = [i for i in self.old_items if i.index > 0]
        candidates = []
        for i in valid_items:
            candidates += ShopObject.item_pools[i]
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

            index = my_candidates.index(i)
            my_candidates[index] = None
            my_candidates = [c for c in my_candidates if c is not i]
            if not duplicates_allowed:
                my_candidates = [c for c in my_candidates
                                 if c not in new_items]
            index = my_candidates.index(None)
            my_candidates[index] = i
            assert my_candidates.count(i) == 1

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

    def preclean(self):
        if self.index == 0xd:
            flame_chrysm = AcquireItemMixin.get_item_by_type_index(1, 0x47)
            assert 'Flame Chrysm' in flame_chrysm.name
            if flame_chrysm not in self.items:
                new_items = list(self.items)
                if (len(new_items) >=
                        len(self.old_data['item_type_item_indexes'])):
                    to_remove = random.choice(new_items)
                    new_items.remove(to_remove)
                new_items = [flame_chrysm] + new_items
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

        self.num_items = len([i for i in self.item_type_item_indexes if i])

        while len(self.items) < len(self.old_data['item_type_item_indexes']):
            self.item_type_item_indexes.append(0)


class MasterSkillsObject(TableObject):
    flag = 'm'
    flag_description = 'masters'
    custom_random_enable = 'm'

    RESTRICTED_NAMES = ['Bais', 'Lang', 'Lee', 'Wynn']

    @classproperty
    def after_order(self):
        return [BaseStatsObject]

    def __repr__(self):
        if self.name in self.RESTRICTED_NAMES:
            return ''

        s = ''
        for level, skill in zip(self.levels, self.skills):
            s += 'LV{0:0>2} {1}\n'.format(level, skill.name)
        return s.strip()

    @property
    def levels(self):
        levels =  [skill_level & 0xff for skill_level in self.skill_levels
                   if skill_level >> 8 != 0xff]
        assert all([1 <= level <= 98 for level in levels])
        return levels

    @property
    def skills(self):
        return [AbilityObject.get(skill_level >> 8)
                for skill_level in self.skill_levels
                if skill_level >> 8 != 0xff]

    @property
    def name(self):
        return MasterStatsObject.names[self.index]

    def set_skills(self, skills, levels):
        skill_indexes = [a.index for a in skills]
        temp_levels = sorted(levels)
        assert len(skill_indexes) == len(levels)
        while len(skill_indexes) < len(self.old_data['skill_levels']):
            skill_indexes.append(0xFF)
            temp_levels.append(0x63)
        self.skill_levels = [
            l | (i << 8) for (i, l) in zip(skill_indexes, temp_levels)]
        assert self.skills == skills
        assert self.levels == levels

    def mutate(self):
        if AbilityObject.flag not in get_flags():
            return
        if self.name in self.RESTRICTED_NAMES:
            return

        banned_skills = {
            AbilityObject.get(l.ability) for l in LevelObject.every
            if l.ability > 0
            and l.charname not in BaseStatsObject.RESTRICTED_NAMES}
        candidates = [a for a in AbilityObject.every if a.rank >= 0
                      and a not in banned_skills and a is a.examine_alt]

        target_nums = [len(mso.skills) for mso in self.every
                       if mso.name not in self.RESTRICTED_NAMES]
        target_num_skills = random.choice(target_nums)
        new_skills = []
        for _ in range(1000):
            if len(new_skills) >= target_num_skills:
                break
            base = random.choice(self.skills)
            assert base.intershuffle_valid
            new_skill = base.get_similar(candidates=candidates,
                                         override_outsider=True,
                                         random_degree=self.random_degree)
            assert new_skill is new_skill.examine_alt
            if new_skill not in new_skills:
                new_skills.append(new_skill)
        else:
            target_num_skills = len(new_skills)
        new_levels = random.choice([mso.levels for mso in self.every
                                    if len(mso.levels) == target_num_skills])
        self.set_skills(new_skills, new_levels)

    @classmethod
    def full_preclean(cls):
        backhand = [a for a in AbilityObject.every
                    if a.old_name == 'Backhand'][0]
        valid_backhand_masters = [
            mso for mso in MasterSkillsObject.every if mso.name not in
            MasterSkillsObject.RESTRICTED_NAMES + ['Hondara']]
        existing = [mso for mso in valid_backhand_masters
                    if backhand in mso.skills]
        if not existing:
            candidates = [mso for mso in valid_backhand_masters
                          if len(mso.skills) < 6]
            chosen = random.choice(candidates)
            skills, levels = chosen.skills, chosen.levels
            candidates = [l for l in range(min(levels), max(levels))
                          if l not in levels]
            if not candidates:
                candidates = [max(levels)+1]
            levels = sorted(levels + [random.choice(candidates)])
            max_index = len(skills)
            skills.insert(random.randint(0, max_index), backhand)
            chosen.set_skills(skills, levels)

        super().full_preclean()

    def preclean(self):
        if self.name in self.RESTRICTED_NAMES:
            return

        for skill in self.skills:
            skill.set_bit('examinable', True)
            skill.reset_skill_type(AbilityObject.EXAMINE_SKILL)

    def cleanup(self):
        if self.name in self.RESTRICTED_NAMES:
            for attr in self.old_data:
                setattr(self, attr, self.old_data[attr])
            return

        for skill in self.skills:
            assert skill.get_bit('examinable')
            assert skill.skill_type & 3 == AbilityObject.EXAMINE_SKILL


class MasterStatsObject(TableObject):
    flag = 'm'
    custom_random_enable = 'm'
    names = [
        'Bunyan', 'Mygas', 'Yggdrasil', "D'lonzo", 'Fahl',
        'Durandal', 'Giotto', 'Hondara', 'Emitai', 'Deis',
        'Hachio', 'Bais', 'Lang', 'Lee', 'Wynn',
        'Ladon', 'Meryleep',
        ]

    def __repr__(self):
        s = 'MASTER {0:0>2X} {1}\n'.format(self.index, self.name)
        for attr, _, _ in self.specsattrs:
            value = getattr(self, attr)
            if value >= 0x80:
                value = value - 0x100
            if value > 0:
                value = '+%s' % value
            s += '{0}: {1:2} | '.format(attr.upper(), value)
        s = s.strip().rstrip('|').strip()
        s = '{0}\n{1}'.format(s, MasterSkillsObject.get(self.index))
        return s.strip()

    def read_data(self, filename=None, pointer=None):
        super().read_data(filename=filename, pointer=pointer)
        for attr in self.old_data:
            value = getattr(self, attr)
            assert self.old_data[attr] == value
            if value >= 0x80:
                value = value - 0x100
            setattr(self, attr, value)
            self.old_data[attr] = value

    @property
    def name(self):
        return self.names[self.index]

    @property
    def rating(self):
        return sum(v for v in self.old_data.values())

    def randomize(self):
        ratings = [mso.rating for mso in self.every]
        target_rating = random.choice(ratings)
        swappable_stats = [('hp', 'ap'), ('pwr', 'dfn', 'agi', 'int')]
        stat_pools = defaultdict(list)
        for attr in self.old_data:
            swappable = [s for s in swappable_stats if attr in s][0]
            for stat in swappable:
                for mso in self.every:
                    stat_pools[attr].append(mso.old_data[stat])
            stat_pools[attr] = sorted(stat_pools[attr])
            setattr(self, attr, random.choice(stat_pools[attr]))

        while True:
            rating = sum(getattr(self, attr) for attr in self.old_data)
            if rating == target_rating:
                break

            attr = random.choice(sorted(self.old_data))
            setattr(self, attr, random.choice(stat_pools[attr]))

    def cleanup(self):
        for attr in self.old_data:
            value = getattr(self, attr)
            if value < 0:
                value = value + 0x100
                assert 0 <= value <= 0xff
                setattr(self, attr, value)


class BaseStatsObject(NameMixin):
    flag = 'c'
    flag_description = 'characters'
    custom_random_enable = 'c'
    RESTRICTED_NAMES = ['Teepo', 'Whelp']

    randomselect_attributes = [
        'surprise_chance', 'reprisal_chance', 'critical_chance',
        'evasion', 'accuracy']

    def __repr__(self):
        stats = ['hp', 'ap', 'pwr', 'dfn', 'agi', 'int']
        s = '{0:0>2X} {1}\n'.format(self.index, self.name)
        s += ' | '.join('{0:3}: {1:>2}'.format(
            stat.upper(), getattr(self, stat)) for stat in stats) + '\n'
        for l in self.levels:
            if l.ability > 0:
                skill = AbilityObject.get(l.ability)
                s += ' - LV{0:0>2} {1} ({2})\n'.format(l.level,
                                                       skill.name, skill.cost)
        return s.strip()

    @property
    def intershuffle_valid(self):
        return self.name not in self.RESTRICTED_NAMES

    @property
    def all_abilities(self):
        return [AbilityObject.get(a) for a in
                self.healing_abilities + self.assist_abilities +
                self.attack_abilities + self.skills_abilities
                if AbilityObject.get(a).name]

    @cached_property
    def levels(self):
        return [l for l in LevelObject.every if l.index // 99 == self.index]

    @cached_property
    def delevel_stats(self):
        stats = ['hp', 'ap', 'pwr', 'dfn', 'agi', 'int']
        stats_values = {}
        for stat in stats:
            assert self.old_data[stat] == self.old_data['base_%s' % stat]
            stats_values[stat] = self.old_data[stat]

        for i in range(self.level, 1, -1):
            level_data = self.levels[i-1]
            for stat in stats:
                stats_values[stat] -= level_data.get_old_stat(stat)
        return stats_values

    def relevel_stats(self, stats_values=None):
        if not self.levels:
            return stats_values
        if stats_values is None:
            stats_values = self.delevel_stats
        for i in range(self.level + 1):
            level_data = self.levels[i]
            for stat in sorted(stats_values):
                stats_values[stat] += getattr(level_data, stat)
        return stats_values

    def mutate_skills(self):
        if not self.levels:
            return

        base_characters = [bso for bso in BaseStatsObject.every
                           if bso.intershuffle_valid]
        base = random.choice(base_characters)
        base_levels = [l for l in base.levels if l.old_data['ability'] > 0]
        new_skills = []
        elements1 = ['fire', 'ice', 'lightning', 'wind']
        elements2 = ['earth', 'holy']
        elements = elements1 + elements2
        random.shuffle(elements1)
        random.shuffle(elements2)
        shuffled_elements = elements1 + elements2
        skill_type_counts = defaultdict(int)
        SKILL_TYPE_MAX_COUNT = 10
        for l in base_levels:
            l.ability = 0
            for _ in range(1000):
                base_rank = AbilityObject.get(
                    l.old_data['ability']).levelup_alt
                base_misc = AbilityObject.get(
                    random.choice(base_levels).old_data['ability'])

                skill_type = base_misc.calculate_skill_type()
                skill_count = skill_type_counts[skill_type]
                if skill_count >= SKILL_TYPE_MAX_COUNT:
                    assert skill_count == SKILL_TYPE_MAX_COUNT
                    continue

                assert base_rank.index != 0 and base_misc.index != 0
                candidates = [
                    c for c in AbilityObject.every
                    if c.is_offense == base_misc.is_offense
                    and c.is_utility == base_misc.is_utility
                    and c is c.levelup_alt and c.rank >= 0
                    and c.old_name not in AbilityObject.LEVELUP_BANNED_SKILLS]
                for e in shuffled_elements:
                    if base_misc.get_bit(e):
                        index = shuffled_elements.index(e)
                        new_element = elements[index]
                        candidates = [c for c in candidates
                                      if c.get_bit(new_element)]
                        break
                if not candidates:
                    continue

                new_skill = base_rank.get_similar(
                    candidates=candidates, override_outsider=True,
                    random_degree=AbilityObject.random_degree,
                    allow_intershuffle_invalid=True)
                new_skill = new_skill.levelup_alt

                assert base_rank in candidates or new_skill is not base_rank
                if new_skill not in new_skills:
                    if new_skill.skill_type & 3 != AbilityObject.EXAMINE_SKILL:
                        skill_type = new_skill.skill_type & 3
                        count = skill_type_counts[skill_type]
                        if (count >= SKILL_TYPE_MAX_COUNT):
                            continue
                    else:
                        new_skill.reset_skill_type()
                    if new_skill.get_bit('examinable'):
                        new_skill.set_bit('examinable', False)
                    new_skills.append(new_skill)
                    skill_type_counts[skill_type] += 1
                    break

        base_levels = base_levels[:len(new_skills)]
        assert len(new_skills) == len(base_levels)
        base_level_levels = [l.level for l in base_levels]
        lower, upper = min(base_level_levels), max(base_level_levels)
        final_levels = []
        for l in base_level_levels:
            while True:
                l = mutate_normal(l, minimum=lower, maximum=upper,
                                  random_degree=AbilityObject.random_degree)
                if l not in final_levels:
                    final_levels.append(l)
                    break
        final_levels = sorted(set(final_levels))
        assert len(final_levels) == len(new_skills)
        level_skills = dict(zip(final_levels, new_skills))

        for l in self.levels:
            if l.level in level_skills:
                l.ability = level_skills[l.level].index
            else:
                l.ability = 0

    def randomize_resistances(self):
        elemental_resistances = []
        status_resistances = []
        for bso in BaseStatsObject.every:
            if not bso.intershuffle_valid:
                continue
            elemental_resistances += bso.resistances[:5]
            status_resistances += bso.resistances[-3:]
        resistances = (
            [random.choice(elemental_resistances) for _ in range(5)] +
            [5] + [random.choice(status_resistances) for _ in range(3)])
        resistances = [mutate_normal(r, 0, 7, random_degree=self.random_degree)
                       for r in resistances]
        self.resistances = resistances
        assert len(self.resistances) == len(self.old_data['resistances'])

    def mutate_stats(self):
        bases = [bso for bso in BaseStatsObject.every
                 if bso.name not in bso.RESTRICTED_NAMES]
        stats = sorted(self.delevel_stats.keys())
        chosen_bases = {}
        initial_stats = {}
        for s in stats:
            chosen_bases[s] = random.choice(bases)
            for (i, old_l) in enumerate(self.levels):
                if i == 0:
                    continue
                i = mutate_normal(i, 1, 98, random_degree=self.random_degree)
                new_l = chosen_bases[s].levels[i]
                new_value = new_l.get_old_stat(s)
                old_l.set_stat(s, new_value)
                initial_stats[s] = chosen_bases[s].delevel_stats[s]

        new_stats = self.relevel_stats(initial_stats)
        for attr, value in sorted(new_stats.items()):
            assert hasattr(self, attr)
            setattr(self, attr, value)

    def mutate(self):
        super().mutate()
        self.mutate_stats()
        self.randomize_resistances()
        self.reseed('skills')
        if AbilityObject.flag in get_flags():
            self.mutate_skills()

    def cleanup(self):
        weapon = WeaponObject.get(self.weapon)
        if not weapon.get_bit(self.name.lower()) and weapon.name != 'Nothing':
            candidates = [w for w in WeaponObject.ranked if
                          w.get_bit(self.name.lower())]
            temp = [c for c in candidates
                    if bin(c.equipability & 0xF7).count('1') == 1]
            if temp:
                candidates = temp
            self.weapon = candidates[0].index

        for attr in ['shield', 'helmet', 'armor']:
            armor = ArmorObject.get(getattr(self, attr))
            if not armor.get_bit(self.name.lower()):
                setattr(self, attr, 0)

        accessories = [AccessoryObject.get(a) for a in self.accessories]
        accessories = [a for a in accessories if a.get_bit(self.name.lower())]
        accessories = [a.index for a in accessories]
        while len(accessories) < 2:
            accessories.append(0)

        ability_check = (self.flag in get_flags() and
                         AbilityObject.flag in get_flags())
        if ability_check:
            for ability_type in ['healing', 'assist', 'attack', 'skills']:
                setattr(self, '%s_abilities' % ability_type, list([]))

            for l in self.levels:
                if l.ability > 0:
                    skill = AbilityObject.get(l.ability)
                    skill_type = skill.skill_type & 3
                    if self.name not in self.RESTRICTED_NAMES:
                        try:
                            assert not skill.get_bit('examinable')
                            assert skill_type != AbilityObject.EXAMINE_SKILL
                        except AssertionError:
                            if MasterSkillsObject.flag not in get_flags():
                                if not hasattr(BaseStatsObject, '_warn_msg'):
                                    print('Warning: Without random masters, '
                                          'skill conflict cannot be resolved.')
                                    BaseStatsObject._warn_msg = True
                            else:
                                raise Exception('Skill conflict.')

                    if l.level <= self.level:
                        if skill_type == AbilityObject.HEALING_SKILL:
                            self.healing_abilities.append(skill.index)
                        elif skill_type == AbilityObject.ASSIST_SKILL:
                            self.assist_abilities.append(skill.index)
                        elif skill_type == AbilityObject.ATTACK_SKILL:
                            self.attack_abilities.append(skill.index)
                        elif skill_type == AbilityObject.EXAMINE_SKILL:
                            self.skills_abilities.append(skill.index)

            for ability_type in ['healing', 'assist', 'attack', 'skills']:
                attr = '%s_abilities' % ability_type
                values = getattr(self, attr)
                assert all(a for a in values)
                assert len(set(values)) == len(values)
                while len(getattr(self, attr)) < len(self.old_data[attr]):
                    getattr(self, attr).append(0)
                assert len(getattr(self, attr)) == len(self.old_data[attr])
        else:
            for ability_type in ['healing', 'assist', 'attack', 'skills']:
                attr = '%s_abilities' % ability_type
                assert getattr(self, attr) == self.old_data[attr]


        for attr in sorted(self.old_data):
            if (attr in ['weapon', 'shield', 'helmet', 'armor', 'accessories']
                    and EquipmentObject.flag in get_flags()):
                continue
            if self.flag not in get_flags():
                assert getattr(self, attr) == self.old_data[attr]
            other_attrs = ['base_%s' % attr, 'current_%s' % attr]
            for other in other_attrs:
                if other in self.old_data:
                    setattr(self, other, getattr(self, attr))

        if self.name == 'Whelp':
            self.attack_abilities = self.old_data['attack_abilities']

        if self.name == 'Ryu':
            for l in LevelObject.every:
                if l.ability > 0:
                    skill = AbilityObject.get(l.ability)
                    if skill.old_name in ['Pilfer', 'Steal']:
                        break
            else:
                pilfer = [a for a in AbilityObject.every
                          if a is a.examine_alt and a.old_name == 'Pilfer'][0]
                pilfer.set_bit('examinable', True)
                pilfer.reset_skill_type(AbilityObject.EXAMINE_SKILL)
                self.skills_abilities.remove(0)
                self.skills_abilities.insert(0, pilfer.index)
                assert (len(self.skills_abilities) ==
                        len(self.old_data['skills_abilities']))

        if 'easymodo' in get_activated_codes() or self.name == 'Whelp':
            self.accuracy = 100
            self.base_accuracy = 100
            self.current_hp = 999
            self.max_hp = 999
            self.base_max_hp = 999


class BaseStats2Object(TableObject):
    @classproperty
    def after_order(self):
        return [BaseStatsObject]

    def cleanup(self):
        for attr in self.old_data:
            assert (self.old_data[attr] ==
                    BaseStatsObject.get(self.index).old_data[attr])
            setattr(self, attr, getattr(BaseStatsObject.get(self.index), attr))


class ManilloStockObject(TableObject):
    def __repr__(self):
        s = 'TRADER {0:0>2X} ({1})\n'.format(self.index, self.name.upper())
        for t in self.trades:
            s += '  %s\n' % t
        return s.strip()

    @property
    def name(self):
        return {
            0: 'Farm',
            2: 'Tower',
            7: 'Urkan Tapa',
            9: 'Dauna Mine',
            0xb: 'Cliff',
            0xd: 'Steel Beach',
            0xf: 'Kombinat',
            }[self.index]

    @property
    def trades(self):
        return [ManilloItemObject.get(i)
                for i in self.trade_indexes if i != 0xFF]


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

    @property
    def area_name(self):
        if hasattr(self, '_area_name'):
            return self._area_name

        area_names = {}
        with open(path.join(tblpath, 'names_areas.txt')) as f:
            for line in f:
                index, description = line.strip().split(' ', 1)
                index = int(index)
                if '(' in description:
                    area, location = description.split('(', 1)
                    location = '(' + location
                else:
                    area = description
                    location = ''
                area = area.upper()
                location = location.lower()
                area_names[index] = '{0} {1}'.format(area, location).strip()

        for c in ChestObject.every:
            c._area_name = area_names[c.area_code]

        return self.area_name

    def cleanup(self):
        super().cleanup()

        if 'thinkwell' in get_activated_codes() and self.memory == 2:
            self.item_type, self.item_index = 4, 0xf


class GeneObject(TableObject):
    flag = 'g'
    flag_description = 'dragon gene locations'
    intershuffle_attributes = ['gene_index']

    def cleanup(self):
        if self.gene_index == 0x21:
            assert 'patch_flame_gene.txt' in get_activated_patches()
            self.gene_index = 0
        assert 0 <= self.gene_index <= 0x11


class ChrysmObject(TableObject):
    @classproperty
    def after_order(self):
        return [GeneObject]

    @property
    def gene(self):
        genes = [g for g in GeneObject.every if g.filename == self.filename]
        assert len(genes) == 1
        gene = genes[0]
        assert gene.old_data['gene_index'] == self.old_data['gene_index']
        return gene

    def cleanup(self):
        self.gene_index = self.gene.gene_index


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
    custom_random_enable = 's'

    def __repr__(self):
        fishdesc = ', '.join(
            '{0} x{1}'.format(fish.name, n) for (fish, n) in self.fishes)
        s = '{1} ({2})'.format(self.index, self.item.name, fishdesc)
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
        if not self.is_canonical:
            return

        super().mutate(unique=True)
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
        candidate_fishes = [c for c in candidate_fishes
                            if c.old_data['price'] <= target_fish_value * 2]
        max_index = len(candidate_fishes)-1
        stagnation_counter = 0
        MAX_STAGNATION = 20
        while True:
            index = int(round(
                (random.random() ** (1/self.random_degree)) * max_index))
            replacement_fish = candidate_fishes[index]
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
                stagnation_counter = 0
                new_fishes.remove((replace_fish, replace_quantity))
                new_fishes.append((replacement_fish, replacement_quantity))
            else:
                stagnation_counter += 1
                if stagnation_counter >= MAX_STAGNATION:
                    break
                continue

            current_value = 0
            for (fish, n) in new_fishes:
                if fish is None:
                    continue
                current_value += (fish.old_data['price'] * n)
            if current_value >= target_fish_value:
                break

        new_fishes = sorted(
            new_fishes, key=lambda f: (99999 if f[0] is None else f[0].index))
        self.fish_indexes = [fish.index-0x38 if fish else 0xFF
                             for fish, n in new_fishes]
        self.fish_quantities = [n if fish else 0 for fish, n in new_fishes]


class MonsterObject(DupeMixin, NameMixin):
    flag = 'e'
    flag_description = 'enemies'
    custom_random_enable = 'e'
    custom_difficulty_enable = False
    difficulty_attrs = ['hp', 'ap', 'pwr', 'dfn', 'agi', 'int']
    randomselect_attributes = [
        'hp', 'ap', 'pwr', 'dfn', 'agi', 'int',
        ('steal_item_type', 'steal_item_index', 'steal_rate'),
        ('drop_item_type', 'drop_item_index', 'drop_rate'),
        'resistances']

    mutate_attributes = {
        'hp': (1, 65000),
        'ap': None,
        'pwr': None,
        'dfn': None,
        'agi': None,
        'int': None,
        'steal_rate': None,
        'drop_rate': None,
        }

    RESISTANCES_NAMES = ['Fire', 'Frost', 'Thunder', 'Earth', 'Wind',
                         'Holy', 'Psionic', 'Status', 'Death']

    def __repr__(self):
        s = '{0:0>3X} LV{1:>3} {2}{3}\n'.format(
            self.index, self.level, self.name,
            '' if self.is_canonical else '*')
        stats = ['hp', 'ap', 'pwr', 'dfn', 'agi', 'int']
        s += ' - '.join('{0}:{1}'.format(
            stat.upper(), getattr(self, stat)) for stat in stats) + '\n'
        for i in range(3):
            resistances_names = self.RESISTANCES_NAMES[(i*3):(i*3)+3]
            resistances = self.resistances[(i*3):(i*3)+3]
            s += ' | '.join('{0:7} {1}'.format(
                a, b) for (a, b) in zip(resistances_names, resistances)) + '\n'
        steal_rate = (2**self.steal_rate) / 128 if self.steal_rate else 0
        steal_rate = int(round(steal_rate*100))
        s += 'Steal: {0} {1}%\n'.format(
            self.steal_item.name if self.steal_item else None, steal_rate)
        drop_rate = (2**self.drop_rate) / 128 if self.drop_rate else 0
        drop_rate = int(round(drop_rate*100))
        s += 'Drop: {0} {1}%\n'.format(
            self.drop_item.name if self.drop_item else None, drop_rate)
        skills = []
        for a in sorted(self.abilities, key=lambda x: x.name):
            if a.old_name in ['Nothing', 'Noting'] or not a.old_name:
                continue
            skills.append('{0}{1}'.format(
                a.name, '*' if a.get_bit('examinable') else ''))
        s += ', '.join(skills) + '\n'
        return s.strip()

    @property
    def abilities(self):
        abilities = set(self.initial_skills)
        for i in range(1, 5):
            condition = getattr(self, 'condition%s' % i)
            if condition >= 99:
                assert condition == 99
                continue
            abilities |= set(getattr(self, 'skills%s' % i))
        abilities = [AbilityObject.get(a) for a in sorted(abilities)]
        return abilities

    @property
    def is_boss(self):
        if hasattr(self, '_is_boss'):
            return self._is_boss

        if not self.is_canonical:
            return self.canonical_relative.is_boss

        for m in MonsterObject.every:
            m._is_boss = True

        for f in FormationObject.every:
            if f.appearance_rate == 0:
                continue
            for m in f.enemies:
                if m is not None:
                    m._is_boss = False

        return self.is_boss

    @property
    def rank(self):
        if hasattr(self, '_rank'):
            return self._rank

        if not self.name:
            return -1

        if not self.is_canonical:
            return self.canonical_relative.rank

        canons = [m for m in MonsterObject.every if m.is_canonical and m.name]
        canons = sorted(canons, key=lambda m: (m.signature, m.index))

        by_hp = sorted(canons, key=lambda m: m.old_data['hp'])
        by_level = sorted(canons, key=lambda m: m.old_data['level'])
        by_exp = sorted(canons, key=lambda m: m.old_data['exp'])
        max_index = len(canons)-1

        for n, m in enumerate(by_hp):
            m._hp_rank = n / max_index

        for n, m in enumerate(by_level):
            m._level_rank = n / max_index

        for n, m in enumerate(by_exp):
            m._exp_rank = n / max_index

        for m in canons:
            ranks = []
            if 1 <= m.old_data['hp'] <= 0xFFFE:
                ranks.append(m._hp_rank)
            if 1 <= m.old_data['level']:
                ranks.append(m._level_rank)

            if 1 <= m.old_data['exp']:
                ranks.append(m._exp_rank)
            elif 1 <= m.old_data['hp'] <= 0xFFFE:
                ranks.append(max(m._hp_rank, m._level_rank))

            m._rank = sum(ranks) / len(ranks)

        return self.rank

    @property
    def intershuffle_valid(self):
        return self.name and self.is_canonical and not self.is_boss

    def mutate_resistances(self):
        elemental_resistances = self.resistances[:5]
        status_resistances = self.resistances[-3:]
        random.shuffle(elemental_resistances)
        random.shuffle(status_resistances)
        self.resistances[:5] = elemental_resistances
        self.resistances[-3:] = status_resistances
        self.resistances = [
            mutate_normal(r, 0, 7, random_degree=self.random_degree)
            for r in self.resistances]

    @property
    def steal_item(self):
        if self.steal_rate == 0:
            return None
        item = ChestObject.get_item_by_type_index(self.steal_item_type,
                                                  self.steal_item_index)
        return item

    @property
    def drop_item(self):
        if self.drop_rate == 0:
            return None
        item = ChestObject.get_item_by_type_index(self.drop_item_type,
                                                  self.drop_item_index)
        return item

    def mutate_loot(self):
        item = self.steal_item
        if item is not None:
            item = item.get_similar(random_degree=ChestObject.random_degree)
            self.steal_item_type = ItemMixin.item_type_from_item(item)
            self.steal_item_index = item.index

        item = self.drop_item
        if item is not None:
            item = item.get_similar(random_degree=ChestObject.random_degree)
            self.drop_item_type = ItemMixin.item_type_from_item(item)
            self.drop_item_index = item.index

    def mutate_skills(self):
        if not self.intershuffle_valid:
            return

        ai_swap = self.get_similar(
            random_degree=MonsterAbilityObject.random_degree)
        self.initial_skills = list(getattr(ai_swap, 'initial_skills'))
        for i in range(1, 5):
            for attr in ['condition', 'ai_unknown', 'skills']:
                attr = '%s%s' % (attr, i)
                setattr(self, attr, ai_swap.old_data[attr])

        existing_skills = set([])
        for attr in ['initial_skills',
                     'skills1', 'skills2', 'skills3', 'skills4']:
            skills = [AbilityObject.get(s) for s in getattr(self, attr)]
            existing_skills |= set(skills)

        existing_skills = sorted(existing_skills, key=lambda s: s.index)
        skill_map = {}
        for existing in existing_skills:
            if existing.rank < 0:
                skill_map[existing.index] = existing.index
                continue

            candidates = [s for s in AbilityObject.ranked if s is s.examine_alt
                          and existing.is_offense == s.is_offense
                          and existing.is_utility == s.is_utility
                          and s.rank >= 0]
            new_skill = existing.examine_alt.get_similar(
                candidates, random_degree=MonsterAbilityObject.random_degree)
            skill_map[existing.index] = new_skill.index

        for attr in ['initial_skills',
                     'skills1', 'skills2', 'skills3', 'skills4']:
            skills = [skill_map[s] for s in getattr(self, attr)]
            setattr(self, attr, skills)

    def mutate(self):
        if self.is_canonical:
            super().mutate()
            self.mutate_resistances()
            self.mutate_loot()
            self.reseed('skills')

    def difficulty_boost(self):
        if self.random_difficulty == 1.0:
            return

        monsters = [m for m in MonsterObject.ranked
                    if m.is_canonical and m.rank >= 0]
        if self not in monsters:
            return

        if self.random_difficulty > 1.0:
            difficulty = self.random_difficulty - 1
            index = monsters.index(self)
            ranked_ratio = index / (len(monsters)-1)
            difficulty = (difficulty * ranked_ratio) + 1
        else:
            difficulty = self.random_difficulty

        for diffattr in self.difficulty_attrs:
            value = getattr(self, diffattr)
            value = int(round(value * random.uniform(1.0, difficulty)))
            if diffattr == 'hp':
                value2 = int(round(value * random.uniform(1.0, difficulty)))
                value = max(value, value2)

            length = [l for (attr, l, _) in self.specsattrs
                      if attr == diffattr][0]
            assert 1 <= length <= 2
            if length == 1:
                value = min(value, max(0xFE, self.old_data[diffattr]))
            elif length == 2:
                value = min(value, max(0xFFFE, self.old_data[diffattr]))

            setattr(self, diffattr, value)

        new_resistances = []
        for r in self.resistances:
            assert 0 <= r <= 7
            r = int(round(r * random.uniform(1.0, difficulty)))
            r = max(0, min(r, 7))
            new_resistances.append(r)
        self.resistances = new_resistances

    def preclean(self):
        self.reseed('difficulty')
        self.difficulty_boost()

        if self.is_boss and self.random_difficulty >= 1.0:
            for attr in self.difficulty_attrs:
                value = getattr(self, attr)
                value = max(value, self.old_data[attr])
                setattr(self, attr, value)

        if self.name in ['Gary', 'Mogu']:
            for attr in self.difficulty_attrs:
                setattr(self, attr, self.old_data[attr])

    def cleanup(self):
        if ChestObject.flag not in get_flags():
            for attr in ['steal_item_index', 'steal_item_type', 'steal_rate',
                         'drop_item_index', 'drop_item_type', 'drop_rate']:
                setattr(self, attr, self.old_data[attr])

        super().cleanup()

        if 'easymodo' in get_activated_codes():
            self.hp = min(self.old_data['hp'], 1)


def write_seed_number():
    seed1 = 'Seed: {0}'.format(get_seed())
    while len(seed1) < addresses.seed1len:
        seed1 += ' '
    assert len(seed1) == addresses.seed1len
    seed2 = '{0}'.format(get_seed())
    while len(seed2) < addresses.seed2len:
        seed2 += ' '
    assert len(seed2) == addresses.seed2len
    seed1 = seed1.encode('ascii').replace(b' ', b'\xff')
    seed1 = seed1.replace(b':', b'\x8f')
    seed2 = seed2.encode('ascii').replace(b' ', b'\xff')

    a = get_open_file('BIN/ETC/AFLDKWA.EMI', sandbox=True)
    b = get_open_file('BIN/ETC/FIRST.EMI', sandbox=True)
    a.seek(addresses.seed1a)
    a.write(seed1)
    a.seek(addresses.seed2a)
    a.write(seed2)
    b.seek(addresses.seed1b)
    b.write(seed1)
    b.seek(addresses.seed2b)
    b.write(seed2)


def activate_blue_magician_code():
    abilities = set([])
    for m in MonsterObject.every:
        if m.is_canonical:
            abilities |= set(m.abilities)

    for l in LevelObject.every:
        if (l.charname not in BaseStatsObject.RESTRICTED_NAMES
                and l.ability > 0):
            a = AbilityObject.get(l.ability)
            abilities -= {a}

    for a in sorted(abilities):
        a.set_bit('examinable', True)
        a.reset_skill_type(AbilityObject.EXAMINE_SKILL)


def activate_feyday(filename):
    f = open(filename)

    names = sorted({line.strip() for line in f.readlines() if line.strip()})
    if any(len(name) > 5 for name in names):
        print('Warning: Name longer than 5 characters.')

    FairyObject.class_reseed('names')
    random.shuffle(names)
    faeries = [fo for fo in FairyObject.every if fo.is_canonical]
    random.shuffle(faeries)
    for name, faerie in zip(names, faeries):
        faerie.set_name(name)

    f.close()


def activate_abilonym(filename):
    with open(filename) as f:
        for line in f:
            if '#' in line:
                line, _ = line.split('#', 1)
            line = line.strip()
            if not line:
                continue

            if ' ' not in line:
                index, name = line, ''
            else:
                index, name = line.split(' ', 1)
            index, name = index.strip(), name.strip()
            index = int(index, 0x10)
            a = AbilityObject.get(index)
            a._rename = name


def write_spoiler(all_objects):
    SPOILER_FILENAME = 'bof3r_spoiler_{0}.txt'.format(get_seed())
    f = open(SPOILER_FILENAME, 'w+')

    f.write('{0} v{1} {2} {3} {4} {5}\n'.format(
        get_global_label(), VERSION, get_flags(), get_seed(),
        get_random_degree()**0.5, get_difficulty()))

    all_objects = sorted(all_objects, key=lambda x: x.__name__)
    random_degrees = [(o.random_degree**0.5) for o in all_objects]
    if len(set(random_degrees)) > 1:
        f.write('R:{0}\n'.format(' '.join('%s' % rd for rd in random_degrees)))
    random_diffs = [o.random_difficulty for o in all_objects]
    if len(set(random_diffs)) > 1:
        f.write('D:{0}\n'.format(' '.join('%s' % rd for rd in random_diffs)))

    f.write('\n1. MASTERS\n'
            '2. CHARACTERS\n'
            '3. MONSTERS\n'
            '4. SHOPS\n'
            '5. MANILLOS\n'
            '6. CHESTS\n\n')

    f.write('1. MASTERS\n\n')
    for mso in MasterStatsObject.every:
        f.write(str(mso) + '\n\n')

    f.write('2. CHARACTERS\n\n')
    for bso in BaseStatsObject.every:
        f.write(str(bso) + '\n\n')

    f.write('3. MONSTERS\n\n')
    for m in sorted(MonsterObject.every, key=lambda x: x.name):
        if m.is_canonical:
            f.write(str(m) + '\n\n')

    f.write('4. SHOPS\n\n')
    for s in ShopObject.every:
        f.write(str(s) + '\n\n')

    f.write('5. MANILLOS\n\n')
    for mso in ManilloStockObject.every:
        if mso.trades:
            f.write(str(mso) + '\n\n')

    f.write('6. CHESTS\n\n')
    areas = {c.area_code for c in ChestObject.every}
    for a in sorted(areas):
        chests = [c for c in ChestObject.every if c.area_code == a]
        if not chests:
            continue
        area_name = chests[0].area_name
        f.write('AREA {0} {1}\n'.format(a, area_name))
        for c in chests:
            f.write(str(c) + '\n')
        f.write('\n')

    f.close()


def write_cue_file():
    filename = get_outfile()
    cue_filename = '.'.join(filename.split('.')[:-1] + ['cue'])
    f = open(cue_filename, 'w+')
    f.write('FILE "{0}" BINARY\n\n'
            'TRACK 01 MODE2/2352\n\n'
            'INDEX 01 00:00:00\n'.format(filename))
    f.close()


def rewrite_master_list():
    if MasterStatsObject.flag not in get_flags():
        return

    f = get_open_file('BIN/ETC/AFLDKWA.EMI', sandbox=True)
    f.seek(addresses.master_list_afldkwa)
    messages = []
    message = b''
    while len(messages) < 17:
        peek = f.read(1)
        if peek == b'\x00':
            messages.append(message)
            message = b''
        else:
            message += peek

    def format_entry(mso, entry, short=False):
        if entry is None:
            return '{0:3}{1:2}'.format('', '')

        sign, attr = entry
        value = abs(getattr(mso, attr))
        if attr == 'dfn':
            attr = 'Def'
        elif attr in ['hp', 'ap']:
            attr = attr.upper()
        else:
            attr = attr[0].upper() + attr[1:]

        attr = attr[:2]
        if short:
            if sign == '+':
                return '$BLUE${0:2}{2}'.format(attr, sign, value)
            elif sign == '-':
                return '$RED${0:2}{2}'.format(attr, sign, value)
        else:
            if sign == '+':
                return '$BLUE${0:3}{1}{2}'.format(attr, sign, value)
            elif sign == '-':
                return '$RED${0:3}{1}{2}'.format(attr, sign, value)

    new_messages = []
    for mso in MasterStatsObject.every:
        plus = [('+', attr) for (attr, _, _) in mso.specsattrs
                if getattr(mso, attr) > 0]
        minus = [('-', attr) for (attr, _, _) in mso.specsattrs
                 if getattr(mso, attr) < 0]
        plus, extra_plus = plus[:4], plus[4:]
        minus, extra_minus = minus[:4], minus[4:]
        plus += [None] * (4-len(plus))
        minus += [None] * (4-len(minus))
        if extra_plus:
            minus[-len(extra_plus):] = extra_plus
        if extra_minus:
            plus[-len(extra_minus):] = extra_minus
        assert len(plus) == len(minus) == 4
        new_message = ''
        short_message = ''
        for left, right in zip(plus, minus):
            if not (left or right):
                continue

            leftstr = format_entry(mso, left)
            rightstr = format_entry(mso, right)
            line = '{0} {1}'.format(leftstr, rightstr)
            line = line.rstrip() + '\n'
            new_message += line

            leftstr = format_entry(mso, left, short=True)
            rightstr = format_entry(mso, right, short=True)
            line = '{0} {1}'.format(leftstr, rightstr)
            line = line.rstrip() + '\n'
            short_message += line

        new_message = new_message.rstrip() + '$NOCOLOR$'
        short_message = short_message.rstrip() + '$NOCOLOR$'

        old_message = messages[len(new_messages)]
        length = len(NameMixin.convert_from_str(new_message))
        shortlength = len(NameMixin.convert_from_str(short_message))
        if length <= len(old_message):
            new_message += ' ' * (len(old_message)-length)
            new_messages.append(new_message)
        elif shortlength <= len(old_message):
            short_message += ' ' * (len(old_message)-shortlength)
            new_messages.append(short_message)
        else:
            shortest_message = '???$NOCOLOR$'
            shortest_message += ' ' * (len(old_message) - 4)
            new_messages.append(shortest_message)
        assert (len(NameMixin.convert_from_str(new_messages[-1]))
                == len(old_message))

    new_messages = [NameMixin.convert_from_str(m) for m in new_messages]
    target_length = sum([len(m) for m in messages])
    current_length = sum([len(m) for m in new_messages])
    assert current_length == target_length
    assert len(messages) == len(new_messages)

    new_data = b'\x00'.join(new_messages)
    f.seek(addresses.master_list_afldkwa)
    f.write(new_data)
    f.close()
    f = get_open_file('BIN/ETC/FIRST.EMI', sandbox=True)
    f.seek(addresses.master_list_first)
    f.write(new_data)
    f.close()


if __name__ == '__main__':
    try:
        print('You are using the Breath of Fire III randomizer,\n'
              '"The Vast and the Violent", version %s.\n' % VERSION)

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]
        codes = {
            'easymodo': ['easymodo'],
            'equipanything': ['equipanything'],
            'feyday': ['feyday', 'faeday'],
            'thinkwell': ['thinkwell'],
            'bluemagician': ['bluemagician', 'bluemage'],
            'abilonym': ['abilonym'],
            }
        run_interface(ALL_OBJECTS, snes=False, codes=codes,
                      custom_degree=True, custom_difficulty=True)

        if 'bluemagician' in get_activated_codes():
            print('SKILL EXAMINE CODE ACTIVATED')
            activate_blue_magician_code()

        if 'thinkwell' in get_activated_codes():
            print('FOUNTAIN PEN CODE ACTIVATED')

        if 'equipanything' in get_activated_codes():
            print('EQUIP ANYTHING CODE ACTIVATED')

        if 'easymodo' in get_activated_codes():
            print('DEBUG MODE ACTIVATED')

        if 'feyday' in get_activated_codes():
            feytxt = input('Faerie names text file? ')
            activate_feyday(feytxt)

        if 'abilonym' in get_activated_codes():
            abiltxt = input('Ability names text file? ')
            activate_abilonym(abiltxt)

        write_seed_number()
        rewrite_master_list()
        clean_and_write(ALL_OBJECTS)

        write_spoiler(ALL_OBJECTS)
        write_cue_file()

        finish_interface()

    except Exception:
        print(format_exc())
        input('Press Enter to close this program. ')
