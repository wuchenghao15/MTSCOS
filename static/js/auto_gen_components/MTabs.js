// MTabs v6.0 - Element Plus Tabs 封装
export default {
  name: 'MTabs',
  props: {', '.join(_props.split(','))},
  emits: {', '.join(_emits.split(','))},
  setup(props, { emit, slots }) {
    return () => {
      return h('div', { class: 'm-{_c.lower()}' }, slots.default ? slots.default() : '');
    };
  },
};
