/**
 * Icons: one family everywhere (Lucide, ISC licence). Imported one by one so only the icons used end up in the app.
 * Use <Icon name="…" /> for plain icons and <IconBadge name="…" /> for an icon in the lemon frame.
 */
import Tag from 'lucide-react-native/icons/tag';
import Play from 'lucide-react-native/icons/play';
import Lightbulb from 'lucide-react-native/icons/lightbulb';
import TriangleAlert from 'lucide-react-native/icons/triangle-alert';
import Pin from 'lucide-react-native/icons/pin';
import Repeat from 'lucide-react-native/icons/repeat';
import Sigma from 'lucide-react-native/icons/sigma';
import ListChecks from 'lucide-react-native/icons/list-checks';
import ALargeSmall from 'lucide-react-native/icons/a-large-small';
import ArrowRight from 'lucide-react-native/icons/arrow-right';
import BookOpen from 'lucide-react-native/icons/book-open';
import Bookmark from 'lucide-react-native/icons/bookmark';
import BookmarkCheck from 'lucide-react-native/icons/bookmark-check';
import ChartColumn from 'lucide-react-native/icons/chart-column';
import Check from 'lucide-react-native/icons/check';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import CircleAlert from 'lucide-react-native/icons/circle-alert';
import CircleCheck from 'lucide-react-native/icons/circle-check';
import CircleUserRound from 'lucide-react-native/icons/circle-user-round';
import CircleX from 'lucide-react-native/icons/circle-x';
import ClipboardList from 'lucide-react-native/icons/clipboard-list';
import Download from 'lucide-react-native/icons/download';
import Flag from 'lucide-react-native/icons/flag';
import Flame from 'lucide-react-native/icons/flame';
import House from 'lucide-react-native/icons/house';
import Layers from 'lucide-react-native/icons/layers';
import LibraryBig from 'lucide-react-native/icons/library-big';
import CalendarDays from 'lucide-react-native/icons/calendar-days';
import ClockCheck from 'lucide-react-native/icons/clock-check';
import Lock from 'lucide-react-native/icons/lock';
import LogOut from 'lucide-react-native/icons/log-out';
import MonitorSmartphone from 'lucide-react-native/icons/monitor-smartphone';
import Moon from 'lucide-react-native/icons/moon';
import NotebookPen from 'lucide-react-native/icons/notebook-pen';
import RotateCcw from 'lucide-react-native/icons/rotate-ccw';
import Settings from 'lucide-react-native/icons/settings';
import Share2 from 'lucide-react-native/icons/share-2';
import Smartphone from 'lucide-react-native/icons/smartphone';
import Sparkles from 'lucide-react-native/icons/sparkles';
import Sun from 'lucide-react-native/icons/sun';
import Target from 'lucide-react-native/icons/target';
import Timer from 'lucide-react-native/icons/timer';
import Trash from 'lucide-react-native/icons/trash';
import Trophy from 'lucide-react-native/icons/trophy';
import UserPen from 'lucide-react-native/icons/user-pen';
import WifiOff from 'lucide-react-native/icons/wifi-off';
import GraduationCap from 'lucide-react-native/icons/graduation-cap';
import PenLine from 'lucide-react-native/icons/pen-line';
import Brain from 'lucide-react-native/icons/brain';
import Calculator from 'lucide-react-native/icons/calculator';
import SearchCheck from 'lucide-react-native/icons/search-check';
import Search from 'lucide-react-native/icons/search';
import X from 'lucide-react-native/icons/x';
import CloudOff from 'lucide-react-native/icons/cloud-off';
import Gauge from 'lucide-react-native/icons/gauge';
import UnfoldVertical from 'lucide-react-native/icons/unfold-vertical';
import BadgeCheck from 'lucide-react-native/icons/badge-check';
import Type from 'lucide-react-native/icons/type';
import ChevronDown from 'lucide-react-native/icons/chevron-down';
import MapIcon from 'lucide-react-native/icons/map';
import Languages from 'lucide-react-native/icons/languages';
import Volume2 from 'lucide-react-native/icons/volume-2';
import VolumeX from 'lucide-react-native/icons/volume-x';
import Bell from 'lucide-react-native/icons/bell';
import BellRing from 'lucide-react-native/icons/bell-ring';
import Gift from 'lucide-react-native/icons/gift';
import CreditCard from 'lucide-react-native/icons/credit-card';
import LockOpen from 'lucide-react-native/icons/lock-open';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { colors } from '../theme';

const ICONS = {
  'a-large-small': ALargeSmall,
  'arrow-right': ArrowRight,
  'book-open': BookOpen,
  bookmark: Bookmark,
  'bookmark-check': BookmarkCheck,
  'chart-column': ChartColumn,
  check: Check,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'circle-alert': CircleAlert,
  'circle-check': CircleCheck,
  'circle-user-round': CircleUserRound,
  'circle-x': CircleX,
  'clipboard-list': ClipboardList,
  download: Download,
  flag: Flag,
  flame: Flame,
  house: House,
  layers: Layers,
  'library-big': LibraryBig,
  lock: Lock,
  'log-out': LogOut,
  'monitor-smartphone': MonitorSmartphone,
  moon: Moon,
  'notebook-pen': NotebookPen,
  'rotate-ccw': RotateCcw,
  calendar: CalendarDays,
  'time-spent': ClockCheck,
  settings: Settings,
  'share-2': Share2,
  smartphone: Smartphone,
  sparkles: Sparkles,
  sun: Sun,
  target: Target,
  'tag': Tag,
  'play': Play,
  'lightbulb': Lightbulb,
  'triangle-alert': TriangleAlert,
  'pin': Pin,
  'repeat': Repeat,
  'sigma': Sigma,
  'list-checks': ListChecks,
  timer: Timer,
  trash: Trash,
  trophy: Trophy,
  'user-pen': UserPen,
  'wifi-off': WifiOff,
  'graduation-cap': GraduationCap,
  'pen-line': PenLine,
  'brain': Brain,
  'calculator': Calculator,
  'search-check': SearchCheck,
  search: Search,
  x: X,
  'cloud-off': CloudOff,
  'gauge': Gauge,
  'unfold-vertical': UnfoldVertical,
  'badge-check': BadgeCheck,
  'type': Type,
  'chevron-down': ChevronDown,
  'map': MapIcon,
  'languages': Languages,
  'volume-2': Volume2,
  'volume-x': VolumeX,
  bell: Bell,
  'bell-ring': BellRing,
  gift: Gift,
  'credit-card': CreditCard,
  'lock-open': LockOpen,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 22, color = colors.ink, strokeWidth = 1.9 }: { name: IconName; size?: number; color?: string; strokeWidth?: number }) {
  const Component = ICONS[name];
  return <Component size={size} color={color} strokeWidth={strokeWidth} />;
}

/** An icon in the lemon frame — used for empty states, stat tiles and list rows, so the whole app looks the same. */
export function IconBadge({ name, size = 44, style }: { name: IconName; size?: number; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[styles.badge, { width: size, height: size, borderRadius: size * 0.32 }, style]}>
      <Icon name={name} size={Math.round(size * 0.5)} color={colors.ink} strokeWidth={2} />
    </View>
  );
}

const styles = StyleSheet.create({
  badge: { backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
});
