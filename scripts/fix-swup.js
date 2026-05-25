// Remove data-swup-reload-script from all scripts to prevent Swup blocking
hexo.extend.filter.register('after_render:html', function(html) {
  return html.replace(/ data-swup-reload-script(?:="")?/g, '');
});
