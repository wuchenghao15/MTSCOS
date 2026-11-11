// MCard v6.0 - Element Plus Card 封装
export default {
  name: 'MCard',
  props: {', '.join(_props.split(','))},
  emits: {', '.join(_emits.split(','))},
  setup(props, { emit, slots }) {
    return () => {
      return h('div', { class: 'm-{_c.lower()}' }, slots.default ? slots.default() : '');
    };
  },
};
