from randomtools.tablereader import (
    TableObject, addresses, get_activated_patches, get_open_file,
    mutate_normal, get_seed)
from randomtools.utils import (
    classproperty, cached_property, utilrandom as random)
from randomtools.interface import (
    run_interface, clean_and_write, finish_interface,
    get_activated_codes, get_flags)
from collections import Counter, defaultdict
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
    @cached_property
    def fingerprint(self):
        return str(sorted(self.old_data.items()))

    @cached_property
    def canonical_relative(self):
        for o in sorted(self.every, key=lambda oo: oo.index):
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


class AbilityObject(NameMixin):
    flag = 'a'
    flag_description = 'abilities'

    HEALING_SKILL = 0
    ASSIST_SKILL = 1
    ATTACK_SKILL = 2
    EXAMINE_SKILL = 3

    @property
    def intershuffle_valid(self):
        if self.rank < 0:
            return False
        return (self._levelup_rank is None
                or self.get_bit('examinable'))

    @property
    def is_spare_levelup_skill(self):
        if len([a for a in self.every if a.name == self.name]) == 1:
            return False
        return not self.intershuffle_valid

    @cached_property
    def canonical(self):
        selves = [a for a in self.every if a.name == self.name]
        if len(selves) == 1:
            return self
        canonicals = [a for a in selves if not a.is_spare_levelup_skill]
        if len(canonicals) > 1:
            canonicals = [a for a in canonicals if a.get_bit('examinable')]
        assert len(canonicals) <= 1
        if canonicals:
            return canonicals[0]
        return None

    @property
    def is_canonical(self):
        return self.canonical is self

    @property
    def is_offense(self):
        return self.get_bit('default_target_enemy')

    @property
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

        max_level = max([max(ms.levels) for ms in MasterSkillsObject.every]) + 1
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

        del(name_ranks['Noting'])
        for a in AbilityObject.every:
            if a.name in name_ranks:
                ranks = name_ranks[a.name]
                a._rank = sum(ranks) / len(ranks)
            else:
                a._rank = -1

        return self.rank


class LevelObject(TableObject):
    @property
    def level(self):
        return (self.index % 99) + 1


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


class MasterSkillsObject(TableObject):
    flag = 'm'
    flag_description = 'masters'

    RESTRICTED_NAMES = ['Bais', 'Lang', 'Lee', 'Wynn']

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
        target_nums = [len(mso.skills) for mso in self.every
                       if mso.name not in self.RESTRICTED_NAMES]
        target_num_skills = random.choice(target_nums)
        new_skills = []
        while len(new_skills) < target_num_skills:
            base = random.choice(self.skills)
            assert base.intershuffle_valid
            new_skill = base.get_similar(random_degree=self.random_degree)
            assert new_skill.is_canonical
            if new_skill not in new_skills:
                new_skills.append(new_skill)
        new_levels = random.choice([mso.levels for mso in self.every
                                    if len(mso.levels) == target_num_skills])
        self.set_skills(new_skills, new_levels)

    def cleanup(self):
        if self.name in self.RESTRICTED_NAMES:
            for attr in self.old_data:
                setattr(self, attr, self.old_data[attr])

        for skill in self.skills:
            assert skill.intershuffle_valid
            skill.set_bit('examinable', True)


class MasterStatsObject(TableObject):
    flag = 'm'
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
        swappable_stats = [('hp', 'ap'), ('str', 'def', 'agi', 'int')]
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
    RESTRICTED_NAMES = ['Teepo', 'Whelp']

    @property
    def intershuffle_valid(self):
        return self.name not in self.RESTRICTED_NAMES

    @property
    def all_abilities(self):
        return [AbilityObject.get(a) for a in
                self.healing_abilities + self.assist_abilities +
                self.attack_abilities + self.skills_abilities
                if AbilityObject.get(a).name]

    @property
    def levels(self):
        return [l for l in LevelObject.every if l.index // 99 == self.index]

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
            while True:
                base_rank = AbilityObject.get(l.old_data['ability']).canonical
                base_misc = AbilityObject.get(
                    random.choice(base_levels).old_data['ability'])

                skill_type = base_misc.calculate_skill_type()
                skill_count = skill_type_counts[skill_type]
                if skill_count >= SKILL_TYPE_MAX_COUNT:
                    assert skill_count == SKILL_TYPE_MAX_COUNT
                    continue

                assert base_rank.index != 0 and base_misc.index != 0
                candidates = [c for c in AbilityObject.every
                              if c.is_offense == base_misc.is_offense
                              and c.is_utility == base_misc.is_utility
                              and c.is_canonical and c.rank >= 0]
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

                assert base_rank in candidates or new_skill is not base_rank
                if new_skill not in new_skills:
                    new_skills.append(new_skill)
                    skill_type_counts[skill_type] += 1
                    break

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

    def mutate(self):
        super().mutate()
        if AbilityObject.flag in get_flags():
            self.mutate_skills()

    @classmethod
    def consume_spares(self):
        spares = [a for a in AbilityObject.every if a.is_spare_levelup_skill]
        spares += [a for a in AbilityObject.every if a.name == 'Noting'
                   and a._monster_rank is None]
        skill_levels = [l for b in BaseStatsObject.every for l in b.levels
                        if b.name not in self.RESTRICTED_NAMES
                        and l.ability > 0]
        skills = set(AbilityObject.get(l.ability) for l in skill_levels)

        if len(skills) > len(spares):
            for mso in MasterSkillsObject.every:
                skills -= set(mso.skills)

        assert not set(skills) & set(spares)
        skills = sorted(skills, key=lambda s: (s.rank, s.index))
        if len(skills) > len(spares):
            skills = skills[-len(spares):]
        assert len(spares) >= len(skills)
        skill_map = {}
        for s in skills:
            spare = spares.pop()
            spare.copy_data(s)
            assert spare.name == s.name
            spare.set_bit('examinable', False)
            spare.reset_skill_type()
            s.reset_skill_type(AbilityObject.EXAMINE_SKILL)
            assert spare.skill_type & 3 != AbilityObject.EXAMINE_SKILL
            skill_map[s.index] = spare.index

        for sl in skill_levels:
            assert sl.ability > 0
            if sl.ability in skill_map:
                sl.ability = skill_map[sl.ability]

    @classmethod
    def full_cleanup(self):
        if AbilityObject.flag in get_flags() and self.flag in get_flags():
            self.consume_spares()
        super().full_cleanup()

    def cleanup(self):
        for ability_type in ['healing', 'assist', 'attack', 'skills']:
            setattr(self, '%s_abilities' % ability_type, list([]))

        for l in self.levels:
            if l.level <= self.level and l.ability > 0:
                skill = AbilityObject.get(l.ability)
                skill_type = skill.skill_type & 3
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
            assert all(a for a in getattr(self, attr))
            assert len(set(getattr(self, attr))) == len(getattr(self, attr))
            while len(getattr(self, attr)) < len(self.old_data[attr]):
                getattr(self, attr).append(0)
            assert len(getattr(self, attr)) == len(self.old_data[attr])

        # TODO: clean up stats modified by equipment
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


class MonsterObject(DupeMixin, NameMixin):
    flag = 'e'
    flag_description = 'enemies'

    def __repr__(self):
        s = 'MONSTER {0:0>3X}{1} {2}\n'.format(
            self.index, '*' if self.is_canonical else ' ', self.name)
        for a in self.abilities:
            if not a.name:
                continue
            s += ' - {0}\n'.format(a.name)
        return s.strip()

    @property
    def abilities(self):
        abilities = set(self.initial_skills)
        for i in range(1, 5):
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
        return self.name and not self.is_boss

    def cleanup(self):
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


if __name__ == '__main__':
    try:
        print('You are using the Breath of Fire III '
              'randomizer version %s.' % VERSION)

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]
        codes = {
            'easymodo': ['easymodo'],
            }
        run_interface(ALL_OBJECTS, snes=False, codes=codes,
                      custom_degree=True)

        write_seed_number()
        clean_and_write(ALL_OBJECTS)

        finish_interface()

    except Exception:
        print(format_exc())
        input('Press Enter to close this program. ')
