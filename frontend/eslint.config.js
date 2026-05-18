import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/set-state-in-effect': 'off',
      // 미사용 변수 — _로 시작하면 허용
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // any 허용 (기존 코드에 많음)
      '@typescript-eslint/no-explicit-any': 'off',
      // 빈 함수 허용
      '@typescript-eslint/no-empty-function': 'off',
    },
  },
  { ignores: ['dist/', 'node_modules/'] },
);
