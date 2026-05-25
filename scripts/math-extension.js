// Protect math expressions from hexo-renderer-marked processing
hexo.extend.filter.register('marked:extensions', function(extensions) {
  // Block math: $$...$$
  extensions.push({
    name: 'mathBlock',
    level: 'block',
    start(src) { var match = src.match(/\$\$/); return match ? match.index : undefined; },
    tokenizer(src) {
      var match = src.match(/^\$\$([\s\S]+?)\$\$/);
      if (match) return { type: 'mathBlock', raw: match[0], text: match[1].trim() };
    },
    renderer(token) { return '\n$$' + token.text + '$$\n'; }
  });
  // Inline math: $...$ (not $$)
  extensions.push({
    name: 'mathInline',
    level: 'inline',
    start(src) { var match = src.match(/(?<!\$)\$(?!\$)/); return match ? match.index : undefined; },
    tokenizer(src) {
      var match = src.match(/^\$(?!\$)((?:[^$\\]|\\.)+?)\$(?!\$)/);
      if (match) return { type: 'mathInline', raw: match[0], text: match[1].trim() };
    },
    renderer(token) { return '$' + token.text + '$'; }
  });
});
